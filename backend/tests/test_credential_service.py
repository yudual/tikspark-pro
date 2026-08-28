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
        # 模拟本次网络嗅探只抓到了好友 A 和 新好友 C，没有抓到 好友 B
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

        synced = self.service._sync_friends_to_db(self.db, self.account, incoming)
        self.db.commit()

        # 验证好友 B 仍然安然无恙，没有被物理误删
        all_friends = self.db.query(Friend).filter(Friend.account_id == self.account.id).all()
        self.assertEqual(len(all_friends), 3)

        friend_b = self.db.query(Friend).filter(Friend.friend_dy_id == "friend_b_id").one()
        self.assertEqual(friend_b.friend_nickname, "好友B")

        friend_a = self.db.query(Friend).filter(Friend.friend_dy_id == "friend_a_id").one()
        self.assertEqual(friend_a.friend_nickname, "好友A(改名)")


if __name__ == "__main__":
    unittest.main()
