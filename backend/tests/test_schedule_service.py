"""自动计划时间计算单元测试。

覆盖：当天窗口、窗口已过、跨天窗口、频率间隔、冷却、失败重试时间。
"""

import unittest
from datetime import datetime, timedelta

from backend.app.services.schedule_service import (
    compute_friend_next_run_at,
    compute_next_run_at,
    compute_retry_run_at,
    get_local_now,
    normalize_schedule_window,
    validate_schedule_window,
)

NOW = datetime(2026, 8, 16, 10, 0, 0)


class ScheduleWindowTests(unittest.TestCase):
    def test_window_later_today(self):
        next_run = compute_next_run_at("14:00-16:00", now=NOW)
        self.assertGreaterEqual(next_run, datetime(2026, 8, 16, 14, 0, 0))
        self.assertLess(next_run, datetime(2026, 8, 16, 16, 0, 0))

    def test_window_already_passed_today_goes_tomorrow(self):
        next_run = compute_next_run_at("08:00-09:00", now=NOW)
        self.assertGreaterEqual(next_run, datetime(2026, 8, 17, 8, 0, 0))
        self.assertLess(next_run, datetime(2026, 8, 17, 9, 0, 0))

    def test_cross_midnight_window_within_range(self):
        next_run = compute_next_run_at("21:00-02:00", now=datetime(2026, 8, 16, 23, 0, 0))
        self.assertGreaterEqual(next_run, datetime(2026, 8, 16, 23, 0, 0))
        self.assertLess(next_run, datetime(2026, 8, 17, 2, 0, 0))

    def test_cross_midnight_window_already_passed(self):
        next_run = compute_next_run_at("21:00-02:00", now=datetime(2026, 8, 16, 3, 0, 0))
        self.assertGreaterEqual(next_run, datetime(2026, 8, 16, 21, 0, 0))
        self.assertLess(next_run, datetime(2026, 8, 17, 2, 0, 0))

    def test_invalid_window_falls_back_to_default(self):
        self.assertEqual("06:00-08:00", normalize_schedule_window(""))
        self.assertEqual("06:00-08:00", normalize_schedule_window("garbage"))
        with self.assertRaises(ValueError):
            validate_schedule_window("06:00-06:00")


class FriendScheduleTests(unittest.TestCase):
    def test_frequency_days_respected(self):
        last_run = datetime(2026, 8, 14, 9, 0, 0)
        next_run = compute_friend_next_run_at(
            schedule_window="06:00-08:00",
            now=NOW,
            frequency_days=3,
            last_run_at=last_run,
        )
        self.assertGreaterEqual(next_run, datetime(2026, 8, 17, 6, 0, 0))
        self.assertLess(next_run, datetime(2026, 8, 17, 8, 0, 0))

    def test_cooldown_minutes_respected(self):
        last_run = NOW - timedelta(minutes=10)
        next_run = compute_friend_next_run_at(
            schedule_window="06:00-08:00",
            now=NOW,
            cooldown_minutes=30,
            last_run_at=last_run,
        )
        self.assertGreaterEqual(next_run, last_run + timedelta(minutes=30))

    def test_retry_run_at_uses_cooldown(self):
        retry = compute_retry_run_at(now=NOW, retry_cooldown_minutes=30)
        self.assertEqual(NOW + timedelta(minutes=30), retry)


class LocalNowTests(unittest.TestCase):
    def test_local_now_is_beijing_naive(self):
        now = get_local_now()
        utc_now = datetime.utcnow()
        delta = (now - utc_now).total_seconds()
        self.assertGreater(delta, 7 * 3600)
        self.assertLess(delta, 9 * 3600)


if __name__ == "__main__":
    unittest.main()
