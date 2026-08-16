"""调度扫描集成测试。

验证"扫描 → 生成计划 → 派发到点好友 → 写执行队列与历史 → 更新下次计划"全链路。
使用临时 SQLite，手动复核模式开启，绝不发送真实消息。
"""

import os
import tempfile
import unittest
from datetime import timedelta

os.environ.setdefault("TIKSPARK_SQLITE_PATH", os.path.join(tempfile.mkdtemp(prefix="tikspark-test-"), "tikspark.db"))
os.environ.setdefault("TIKSPARK_SECRET_KEY_PATH", os.path.join(tempfile.mkdtemp(prefix="tikspark-test-"), "secret.key"))
os.environ.setdefault("TIKSPARK_ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("TIKSPARK_SCHEDULER_ENABLED", "false")
os.environ.setdefault("TIKSPARK_MANUAL_REVIEW_MODE", "true")

from backend.app.database import SessionLocal  # noqa: E402
from backend.app.models import (  # noqa: E402
    Account,
    AccountStatus,
    DispatchSource,
    DispatchTask,
    Friend,
    Message,
    MessageType,
    RunLog,
    RunStatus,
)
from backend.app.services.app_settings_service import (  # noqa: E402
    AUTO_SCHEDULE_ENABLED_KEY,
    set_auto_schedule_enabled,
)
from backend.app.services.schedule_service import get_local_now  # noqa: E402
from backend.app.services.scheduler import run_dispatch_scan  # noqa: E402
from backend.app.state import global_state  # noqa: E402


class SchedulerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.account = Account(
            nickname="集成测试账号",
            dy_id="99999",
            cookie_text="encrypted-fake",
            status=AccountStatus.healthy,
        )
        self.db.add(self.account)
        self.db.flush()
        self.friend = Friend(
            account_id=self.account.id,
            friend_nickname="集成测试好友",
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
        set_auto_schedule_enabled(self.db, True)

    def tearDown(self):
        self.db.query(RunLog).filter(RunLog.friend_id == self.friend.id).delete()
        self.db.query(DispatchTask).filter(DispatchTask.friend_id == self.friend.id).delete()
        self.db.delete(self.friend)
        self.db.delete(self.account)
        self.db.commit()
        self.db.close()

    def _mark_due(self):
        self.friend.next_run_at = get_local_now() - timedelta(minutes=1)
        self.db.commit()

    def test_scan_dispatch_and_schedule_advance(self):
        self._mark_due()
        run_dispatch_scan(self.db)

        tasks = self.db.query(DispatchTask).filter(DispatchTask.friend_id == self.friend.id).all()
        self.assertEqual(1, len(tasks))
        self.assertEqual(DispatchSource.auto, tasks[0].source)
        self.assertEqual(RunStatus.manual_review, tasks[0].status)

        logs = self.db.query(RunLog).filter(RunLog.friend_id == self.friend.id).all()
        self.assertEqual(1, len(logs))
        self.assertEqual(RunStatus.manual_review, logs[0].status)

        self.db.refresh(self.friend)
        self.assertIsNotNone(self.friend.last_run_at)
        self.assertIsNotNone(self.friend.next_run_at)
        self.assertGreater(self.friend.next_run_at, get_local_now())

    def test_scan_without_due_friends_does_not_dispatch(self):
        run_dispatch_scan(self.db)

        self.assertEqual(0, self.db.query(DispatchTask).filter(DispatchTask.friend_id == self.friend.id).count())
        self.assertEqual(0, global_state.due_task_total)
        self.db.refresh(self.friend)
        self.assertIsNotNone(self.friend.next_run_at)

    def test_disabled_auto_switch_blocks_dispatch(self):
        from backend.app.models import AppSetting

        setting = self.db.get(AppSetting, AUTO_SCHEDULE_ENABLED_KEY)
        setting.value = "false"
        self.db.commit()

        self._mark_due()
        run_dispatch_scan(self.db)

        self.assertEqual(0, self.db.query(DispatchTask).filter(DispatchTask.friend_id == self.friend.id).count())
        self.assertEqual("自动续火计划已关闭", global_state.status_text)
        setting.value = "true"
        self.db.commit()


if __name__ == "__main__":
    unittest.main()
