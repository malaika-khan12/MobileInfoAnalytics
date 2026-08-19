from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from backend.control_api import create_app
except ModuleNotFoundError as exc:
    if exc.name != "flask":
        raise
    create_app = None


@unittest.skipUnless(create_app is not None, "Flask is not installed in this build environment")
class ControlApiSecurityTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "MOBILE_ANALYTICS_ADMIN_TOKEN": "test-operator-token",
            "FLASK_SECRET_KEY": "test-session-key-that-is-not-used-in-production",
        }, clear=False)
        self.env.start()
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def tearDown(self):
        self.env.stop()

    def test_privileged_metadata_requires_operator_session(self):
        response = self.client.get("/api/data/rejects?limit=5")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Administrator authentication required", response.get_json()["error"])

    def test_operations_require_operator_session(self):
        response = self.client.post("/api/operations", json={"kind": "upload-dry-run"})
        self.assertEqual(response.status_code, 401)

    def test_login_uses_http_only_strict_named_cookie(self):
        response = self.client.post("/api/auth/login", json={"token": "test-operator-token"})
        self.assertEqual(response.status_code, 200)
        cookie = response.headers.get("Set-Cookie", "")
        self.assertIn("mobile_analytics_ops=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

    @patch("backend.control_api.dashboard_payload")
    def test_unauthenticated_dashboard_hides_operational_run_history(self, dashboard):
        dashboard.return_value = {
            "metrics": {"products": 1},
            "sources": [],
            "recent_products": [],
            "price_spreads": [],
            "recent_runs": [{"run_id": 99}],
        }
        response = self.client.get("/api/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("recent_runs", response.get_json())

    @patch("backend.control_api.dashboard_payload")
    def test_authenticated_dashboard_can_include_operational_run_history(self, dashboard):
        dashboard.return_value = {
            "metrics": {"products": 1},
            "sources": [],
            "recent_products": [],
            "price_spreads": [],
            "recent_runs": [{"run_id": 99}],
        }
        self.client.post("/api/auth/login", json={"token": "test-operator-token"})
        response = self.client.get("/api/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["recent_runs"], [{"run_id": 99}])

    @patch("backend.control_api.pipeline_status")
    def test_unauthenticated_health_hides_filesystem_and_job_history(self, status):
        status.return_value = {
            "repo_root": "/secret/repo/path",
            "database": {"configured": True, "reachable": False, "error": "internal project diagnostic", "detail": {"hint": "private"}},
            "scripts": {"upload": {"path": "filestorage/csvToDataBase.py", "exists": True}},
            "jobs": [{"id": "JOB-SECRET"}],
        }
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertNotIn("repo_root", payload)
        self.assertNotIn("jobs", payload)
        self.assertEqual(payload["scripts"], {"upload": {"exists": True}})
        self.assertEqual(payload["database"]["error"], "Database health check failed.")
        self.assertNotIn("detail", payload["database"])


if __name__ == "__main__":
    unittest.main()
