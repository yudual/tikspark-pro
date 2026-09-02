"""派发链路单元测试。

使用独立临时 SQLite 数据库，mock 浏览器执行器，不启动浏览器、不发送真实消息。
"""

import os
import tempfile
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("TIKSPARK_SQLITE_PATH", os.path.join(tempfile.mkdtemp(prefix="tikspark-test-"), "tikspark.db"))

from backend.app.database import Base  # noqa: E402
from backend.app.models import (  # noqa: E402
    Account,
    AccountStatus,
    DispatchTask,
    Friend,
    Message,
    MessageType,
    RunLog,
    RunStatus,
)
from backend.app.services import dispatch_service  # noqa: E402
from backend.app.services.schedule_service import get_local_now  # noqa: E402
from backend.app.time_utils import beijing_now  # noqa: E402


class FakeExecution:
    def __init__(self, result):
        self.result = result

    def send_message(self, account, friend, content):
        return self.result


def _settings(manual_review_mode=False):
    return SimpleNamespace(
        manual_review_mode=manual_review_mode,
        dispatch_jitter_min_seconds=1,
        dispatch_jitter_max_seconds=2,
    )


class DispatchServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="tikspark-dispatch-")
        self.engine = create_engine(f"sqlite:///{self.tmp_dir}/test.db")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()
        self.account = Account(
            nickname="测试账号",
            dy_id="12345",
            cookie_text="encrypted-fake",
            status=AccountStatus.healthy,
        )
        self.db.add(self.account)
        self.db.flush()
        self.friend = Friend(
            account_id=self.account.id,
            friend_nickname="测试好友",
            is_active=True,
            schedule_window="06:00-08:00",
            frequency_days=1,
            cooldown_minutes=0,
            retry_limit=2,
            retry_cooldown_minutes=30,
        )
        self.db.add(self.friend)
        self.db.flush()
        self.db.add(Message(friend_id=self.friend.id, message_type=MessageType.fixed, message_content="今日火花+1"))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _run(self, manual_review_mode=False):
        with (
            patch.object(
                dispatch_service,
                "execution_service",
                FakeExecution(SimpleNamespace(success=True, summary="发送成功", details="已确认")),
            ),
            patch.object(
                dispatch_service,
                "get_settings",
                return_value=_settings(manual_review_mode=manual_review_mode),
            ),
        ):
            return dispatch_service.dispatch_active_messages(self.db)

    def test_success_path_writes_task_and_log_and_schedules_next(self):
        before = get_local_now()
        created = self._run()

        self.assertEqual(1, created)
        task = self.db.query(DispatchTask).one()
        self.assertEqual(RunStatus.success, task.status)
        log = self.db.query(RunLog).one()
        self.assertEqual(RunStatus.success, log.status)
        self.db.refresh(self.friend)
        self.assertGreater(self.friend.next_run_at, before)
        self.assertEqual(0, self.friend.consecutive_failures)

    def test_failure_keeps_retrying_until_limit(self):
        with (
            patch.object(
                dispatch_service,
                "execution_service",
                FakeExecution(SimpleNamespace(success=False, summary="发送失败", details="网络超时")),
            ),
            patch.object(
                dispatch_service,
                "get_settings",
                return_value=_settings(),
            ),
        ):
            dispatch_service.dispatch_active_messages(self.db)

        self.db.refresh(self.friend)
        self.assertEqual(1, self.friend.consecutive_failures)
        self.assertAlmostEqual(
            (self.friend.next_run_at - self.friend.last_run_at).total_seconds(),
            30 * 60,
            delta=2,
        )
        self.assertEqual(RunStatus.failed, self.db.query(RunLog).one().status)

    def test_manual_review_does_not_advance_normal_schedule(self):
        self._run(manual_review_mode=True)

        self.db.refresh(self.friend)
        log = self.db.query(RunLog).one()
        self.assertEqual(RunStatus.manual_review, log.status)
        self.assertEqual(0, self.friend.consecutive_failures)
        self.assertAlmostEqual(
            (self.friend.next_run_at - self.friend.last_run_at).total_seconds(),
            30 * 60,
            delta=2,
        )

    def test_invalid_account_is_skipped_without_retry(self):
        self.account.status = AccountStatus.invalid
        self.db.commit()

        self._run()

        self.db.refresh(self.friend)
        log = self.db.query(RunLog).one()
        self.assertEqual(RunStatus.failed, log.status)
        self.assertEqual("账号凭证失效", log.summary)
        self.assertIsNone(self.friend.next_run_at)



    def test_cookie_is_not_refreshed_on_success(self):
        with (
            patch.object(
                dispatch_service,
                "execution_service",
                FakeExecution(SimpleNamespace(success=True, summary="发送成功", details="已确认", refreshed_cookies="new-refreshed-cookie")),
            ),
            patch.object(
                dispatch_service,
                "get_settings",
                return_value=_settings(),
            ),
        ):
            dispatch_service.dispatch_active_messages(self.db)

        self.db.refresh(self.account)
        self.assertIsNone(self.account.cookie_updated_at)
        self.assertEqual("encrypted-fake", self.account.cookie_text)

    def test_cookie_is_not_refreshed_on_failure(self):
        with (
            patch.object(
                dispatch_service,
                "execution_service",
                FakeExecution(SimpleNamespace(success=False, summary="未找到好友", details="未找到好友", refreshed_cookies="new-refreshed-cookie")),
            ),
            patch.object(
                dispatch_service,
                "get_settings",
                return_value=_settings(),
            ),
        ):
            dispatch_service.dispatch_active_messages(self.db)

        self.db.refresh(self.account)
        self.assertIsNone(self.account.cookie_updated_at)
        self.assertEqual("encrypted-fake", self.account.cookie_text)


if __name__ == "__main__":
    unittest.main()

