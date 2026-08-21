"""API 冒烟测试。

运行前会自动使用临时 SQLite 数据库，不会触碰真实 backend/data。
调度进程关闭、人工复核模式开启，保证测试不会触发真实发送。
"""

import os
import tempfile
import unittest

_TMP_ROOT = tempfile.mkdtemp(prefix="tikspark-test-")
os.environ.setdefault("TIKSPARK_SQLITE_PATH", os.path.join(_TMP_ROOT, "tikspark.db"))
os.environ.setdefault("TIKSPARK_SECRET_KEY_PATH", os.path.join(_TMP_ROOT, "secret.key"))
os.environ.setdefault("TIKSPARK_ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("TIKSPARK_SCHEDULER_ENABLED", "false")
os.environ.setdefault("TIKSPARK_MANUAL_REVIEW_MODE", "true")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402

AUTH_HEADERS = {"Authorization": "Bearer test-admin-token"}


class ApiSmokeTests(unittest.TestCase):
    def setUp(self):
        self._client_ctx = TestClient(app)
        self.client = self._client_ctx.__enter__()

    def tearDown(self):
        self._client_ctx.__exit__(None, None, None)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(200, response.status_code)
        self.assertEqual("ok", response.json()["status"])

    def test_api_requires_admin_token(self):
        for path in (
            "/api/dashboard/summary",
            "/api/accounts",
            "/api/schedule",
            "/api/logs",
            "/api/run/tasks",
            "/api/system/settings",
        ):
            response = self.client.get(path)
            self.assertEqual(401, response.status_code, path)

    def test_dashboard_endpoints(self):
        for path in ("/api/dashboard/summary", "/api/dashboard/system-status"):
            response = self.client.get(path, headers=AUTH_HEADERS)
            self.assertEqual(200, response.status_code, path)

    def test_accounts_and_messages_are_empty_on_fresh_db(self):
        for path in ("/api/accounts", "/api/messages"):
            response = self.client.get(path, headers=AUTH_HEADERS)
            self.assertEqual(200, response.status_code, path)
            self.assertEqual([], response.json())

    def test_schedule_logs_and_run_endpoints(self):
        for path in ("/api/schedule", "/api/schedule/preview", "/api/logs", "/api/run/tasks"):
            response = self.client.get(path, headers=AUTH_HEADERS)
            self.assertEqual(200, response.status_code, path)

    def test_system_settings_exposes_configuration_flags_only(self):
        response = self.client.get("/api/system/settings", headers=AUTH_HEADERS)
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertTrue(payload["admin_token_configured"])
        self.assertFalse(payload["scheduler_enabled"])
        self.assertTrue(payload["manual_review_mode"])
        self.assertNotIn("admin_token", payload)


    def test_run_tasks_and_retry_failed(self):
        resp = self.client.post("/api/run/retry-failed", headers=AUTH_HEADERS)
        self.assertEqual(200, resp.status_code)
        self.assertIn("重试", resp.json()["message"])


if __name__ == "__main__":
    unittest.main()
