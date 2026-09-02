"""凭证与好友安全同步测试。"""

import os
import tempfile
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import Account, AccountStatus, Friend
from backend.app.services.credential_service import CredentialService, UserCandidate


class CredentialServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="tikspark-cred-")
        self.engine = create_engine(f"sqlite:///{self.tmp_dir}/test.db")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()
        self.account = Account(
            nickname="测试主账号",
            dy_id="my_dy_id",
            cookie_text="fake-token",
            status=AccountStatus.healthy,
        )
        self.db.add(self.account)
        self.db.flush()

        # 初始好友 A 和 B
        self.friend_a = Friend(
            account_id=self.account.id,
            friend_dy_id="friend_a_id",
            friend_nickname="好友A",
        )
        self.friend_b = Friend(
            account_id=self.account.id,
            friend_dy_id="friend_b_id",
            friend_nickname="好友B",
        )
        self.db.add(self.friend_a)
        self.db.add(self.friend_b)
        self.db.commit()

        self.service = CredentialService()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_sync_does_not_delete_missing_friends(self):
        # 模拟本次网络嗅探只抓到了好友 A 和 新好友 C，没有抓到 好友 B (非全量同步模式 purge_missing=False)
        incoming = [
            UserCandidate(
                uid="uid_a",
                display_id="friend_a_id",
                nickname="好友A(改名)",
                avatar_url="http://avatar.a",
                remark="",
                source="network",
            ),
            UserCandidate(
                uid="uid_c",
                display_id="friend_c_id",
                nickname="新好友C",
                avatar_url="http://avatar.c",
                remark="",
                source="network",
            ),
        ]

        synced = self.service._sync_friends_to_db(self.db, self.account, incoming, purge_missing=False)
        self.db.commit()

        # 验证好友 B 仍然安然无恙，没有被物理误删
        all_friends = self.db.query(Friend).filter(Friend.account_id == self.account.id).all()
        self.assertEqual(len(all_friends), 3)

        friend_b = self.db.query(Friend).filter(Friend.friend_dy_id == "friend_b_id").one()
        self.assertEqual(friend_b.friend_nickname, "好友B")

        friend_a = self.db.query(Friend).filter(Friend.friend_dy_id == "friend_a_id").one()
        self.assertEqual(friend_a.friend_nickname, "好友A(改名)")

    def test_sync_purges_non_mutual_friends(self):
        # 全量同步模式 (purge_missing=True)，不在列表里的好友会被物理清理
        incoming = [
            UserCandidate(
                uid="uid_a",
                display_id="friend_a_id",
                nickname="好友A",
                avatar_url="http://avatar.a",
                remark="",
                source="spotlight_relation",
            ),
        ]

        synced = self.service._sync_friends_to_db(self.db, self.account, incoming, purge_missing=True)
        self.db.commit()

        all_friends = self.db.query(Friend).filter(Friend.account_id == self.account.id).all()
        self.assertEqual(len(all_friends), 1)
        self.assertEqual(all_friends[0].friend_dy_id, "friend_a_id")

    def test_manual_add_and_update_and_delete_friend(self):
        from backend.app.schemas import FriendCreateRequest, FriendUpdateRequest

        # 1. 手动添加好友
        create_req = FriendCreateRequest(
            friend_nickname="手动好友D",
            friend_dy_id="custom_d_id",
            friend_avatar="http://avatar.d",
            is_active=True,
            schedule_window="07:00-09:00",
            frequency_days=2,
            message_type="fixed",
            message_content="[火花]",
        )
        created = self.service.add_custom_friend(self.db, self.account, create_req)
        self.assertEqual(created.friend_nickname, "手动好友D")
        self.assertEqual(created.schedule_window, "07:00-09:00")
        self.assertTrue(created.is_active)
        self.assertIsNotNone(created.next_run_at)
        self.assertIsNotNone(created.message)
        self.assertEqual(created.message.message_content, "[火花]")

        # 2. 修改好友
        update_req = FriendUpdateRequest(
            friend_nickname="手动好友D(已修改)",
            schedule_window="08:00-10:00",
            message_content="早安[火花]",
        )
        updated = self.service.update_friend(self.db, created, update_req)
        self.assertEqual(updated.friend_nickname, "手动好友D(已修改)")
        self.assertEqual(updated.schedule_window, "08:00-10:00")
        self.assertEqual(updated.message.message_content, "早安[火花]")

        # 3. 删除单个好友
        self.service.delete_friend(self.db, self.friend_b)
        remaining = self.db.query(Friend).filter(Friend.account_id == self.account.id).all()
        self.assertEqual(len(remaining), 2)

        # 4. 批量删除好友
        ids_to_delete = [self.friend_a.id, created.id]
        deleted_count = self.service.batch_delete_friends(self.db, ids_to_delete)
        self.assertEqual(deleted_count, 2)
        all_left = self.db.query(Friend).filter(Friend.account_id == self.account.id).all()
        self.assertEqual(len(all_left), 0)

    def test_cookie_normalization_and_parsing(self):
        # 1. 常见 header 字符串
        raw_header = "Cookie: sessionid=test_session_123; sid_guard=test_guard; passport_csrf_token=csrf_val"
        cookies = self.service._to_playwright_cookies(raw_header)
        self.assertEqual(len(cookies), 3)
        self.assertEqual(cookies[0]["domain"], ".douyin.com")
        self.assertEqual(cookies[0]["path"], "/")

        # 2. JSON 数组 (带各插件导出格式)
        json_array = """[
            {"name": "sessionid", "value": "abc", "domain": "www.douyin.com", "sameSite": "no_restriction"},
            {"name": "passport_csrf_token", "value": "def", "domain": ".douyin.com"}
        ]"""
        cookies_json = self.service._to_playwright_cookies(json_array)
        self.assertEqual(len(cookies_json), 2)
        self.assertEqual(cookies_json[0]["sameSite"], "None")
        self.assertEqual(cookies_json[0]["domain"], "www.douyin.com")

    def test_batch_import_friends(self):
        from backend.app.schemas import FriendBatchImportRequest

        batch_text = """
        小明 12345678
        小红 MS4wLjABAAAA9999
        小张
        """
        req = FriendBatchImportRequest(
            raw_text=batch_text,
            schedule_window="06:00-08:00",
            is_active=True,
            message_content="早安[火花]",
        )
        count = self.service.batch_import_friends(self.db, self.account, req)
        self.assertEqual(count, 3)

        friends = self.db.query(Friend).filter(Friend.account_id == self.account.id).all()
        # 初始有 2 个 + 导入 3 个 = 5 个
        self.assertEqual(len(friends), 5)

        imported_ming = self.db.query(Friend).filter(Friend.friend_dy_id == "12345678").one()
        self.assertEqual(imported_ming.friend_nickname, "小明")
        self.assertEqual(imported_ming.message.message_content, "早安[火花]")
        self.assertTrue(imported_ming.is_active)
        self.assertIsNotNone(imported_ming.next_run_at)


if __name__ == "__main__":
    unittest.main()
