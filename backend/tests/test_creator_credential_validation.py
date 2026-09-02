"""创作者平台 Cookie 登录态判定测试。"""

from backend.app.models import AccountStatus
from backend.app.services.credential_service import CredentialService, UserCandidate


def _candidate(source: str = "self_profile") -> UserCandidate:
    return UserCandidate(
        uid="uid-1",
        display_id="douyin-id",
        nickname="测试账号",
        avatar_url="",
        remark="",
        source=source,
        sec_uid="sec-uid-1",
    )


def test_creator_login_failure_marks_cookie_invalid_even_when_consumer_has_friends():
    service = CredentialService()
    account = _candidate()
    friend = _candidate("spotlight_relation")
    friend.uid = "friend-uid"
    friend.display_id = "friend-id"
    friend.nickname = "好友"

    result = service._build_sync_result(
        account_candidate=account,
        friends=[friend],
        is_login_failed=False,
        creator_login_failed=True,
    )

    assert result.status == AccountStatus.invalid
    assert result.friends == [friend]
    assert "creator.douyin.com" in result.status_reason
    assert "创作者平台私信" in result.status_reason


def test_creator_login_success_allows_healthy_status_with_friends():
    service = CredentialService()
    account = _candidate()
    friend = _candidate("spotlight_relation")
    friend.uid = "friend-uid"
    friend.display_id = "friend-id"

    result = service._build_sync_result(
        account_candidate=account,
        friends=[friend],
        is_login_failed=False,
        creator_login_failed=False,
    )

    assert result.status == AccountStatus.healthy
    assert result.friends == [friend]


def test_consumer_login_failure_remains_invalid():
    service = CredentialService()

    result = service._build_sync_result(
        account_candidate=_candidate(),
        friends=[],
        is_login_failed=True,
        creator_login_failed=False,
    )

    assert result.status == AccountStatus.invalid
    assert "登录态已失效" in result.status_reason
