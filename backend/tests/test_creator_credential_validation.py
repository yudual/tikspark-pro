"""Cookie 更新不得从云服务器主动登录抖音。"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import Account, AccountStatus, Friend
from backend.app.services.credential_service import CredentialService
from backend.app.services.secret_service import get_secret_service


def _db_session():
    tmp_dir = tempfile.TemporaryDirectory(prefix="tikspark-passive-cookie-")
    engine = create_engine(f"sqlite:///{Path(tmp_dir.name) / 'test.db'}")
    Base.metadata.create_all(engine)
    return tmp_dir, engine, sessionmaker(bind=engine)()


def test_cookie_editor_scope_and_attributes_are_preserved():
    service = CredentialService()
    cookies = service._to_playwright_cookies(
        '[{"name":"creator_session","value":"abc",'
        '"domain":"creator.douyin.com","path":"/creator-micro",'
        '"sameSite":"unspecified","secure":true,"httpOnly":true,'
        '"expirationDate":1893456000}]'
    )

    assert cookies == [{
        "name": "creator_session",
        "value": "abc",
        "domain": "creator.douyin.com",
        "path": "/creator-micro",
        "secure": True,
        "httpOnly": True,
        "expires": 1893456000,
    }]


def test_host_only_www_cookie_is_not_broadened_to_all_douyin_subdomains():
    service = CredentialService()
    cookie = service._to_playwright_cookies(
        '[{"name":"sessionid","value":"abc","domain":"www.douyin.com","path":"/"}]'
    )[0]

    assert cookie["domain"] == "www.douyin.com"


def test_import_cookie_does_not_open_browser_or_validate_online():
    tmp_dir, engine, db = _db_session()
    try:
        service = CredentialService()
        with patch.object(service, "_extract_from_cookie") as online_check:
            account = service.import_account(
                db,
                '[{"name":"sessionid","value":"abc","domain":".douyin.com","path":"/"}]',
            )
        online_check.assert_not_called()
        assert account.status == AccountStatus.unknown
        assert "未从阿里云主动登录" in account.status_reason
    finally:
        db.close()
        engine.dispose()
        tmp_dir.cleanup()


def test_update_cookie_does_not_open_browser_and_preserves_friends():
    tmp_dir, engine, db = _db_session()
    try:
        account = Account(
            nickname="原账号",
            dy_id="old-id",
            cookie_text=get_secret_service().encrypt(
                '[{"name":"sessionid","value":"old","domain":".douyin.com","path":"/"}]'
            ),
            status=AccountStatus.healthy,
        )
        db.add(account)
        db.flush()
        friend = Friend(account_id=account.id, friend_dy_id="friend-id", friend_nickname="好友")
        db.add(friend)
        db.commit()

        service = CredentialService()
        with patch.object(service, "_extract_from_cookie") as online_check:
            friends = service.update_account_cookie(
                db,
                account,
                '[{"name":"sessionid","value":"new","domain":"www.douyin.com","path":"/"}]',
            )
        online_check.assert_not_called()
        assert account.status == AccountStatus.unknown
        assert account.nickname == "原账号"
        assert [item.friend_nickname for item in friends] == ["好友"]
    finally:
        db.close()
        engine.dispose()
        tmp_dir.cleanup()


def test_status_check_is_local_only():
    tmp_dir, engine, db = _db_session()
    try:
        account = Account(
            nickname="账号",
            dy_id="id",
            cookie_text=get_secret_service().encrypt(
                '[{"name":"sessionid_ss","value":"abc","domain":".douyin.com","path":"/"}]'
            ),
            status=AccountStatus.healthy,
        )
        db.add(account)
        db.commit()

        service = CredentialService()
        with patch.object(service, "_extract_from_cookie") as online_check:
            result = service.check_account_status(db, account)
        online_check.assert_not_called()
        assert result.status == AccountStatus.unknown
        assert "未从阿里云联网验证" in result.status_reason
    finally:
        db.close()
        engine.dispose()
        tmp_dir.cleanup()
