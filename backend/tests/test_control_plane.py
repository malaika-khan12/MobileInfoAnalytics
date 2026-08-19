from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.control_plane import ControlPlaneError, Job, JobManager, SupabaseREST, build_operation, query_view


class FakeRest:
    def get(self, schema, resource, **kwargs):
        return ([{"product_id": 1, "company_name": "X", "mobile_name": "Y"}], 1)


class ProductionIntegrationTests(unittest.TestCase):
    def test_view_query_is_allowlisted_and_bounded(self):
        result = query_view(FakeRest(), "products", limit=999, offset=-10, search="test")
        self.assertEqual(result["limit"], 100)
        self.assertEqual(result["offset"], 0)
        self.assertEqual(result["total"], 1)

    def test_unknown_view_is_rejected(self):
        with self.assertRaises(ControlPlaneError):
            query_view(FakeRest(), "not_a_real_view")

    def test_scrape_range_builds_argument_array_not_shell_string(self):
        with patch("backend.control_plane._script", side_effect=lambda path: f"/repo/{path}"):
            kind, _label, command, commands = build_operation({
                "kind": "scrape", "source": "mega", "mode": "range",
                "minimum": 2, "maximum": 4, "delay_min": 2, "delay_max": 5,
            })
        self.assertEqual(kind, "scrape")
        self.assertIsNone(commands)
        self.assertIn("--min", command)
        self.assertIn("--max", command)
        self.assertNotIn(";", "".join(command))

    def test_daraz_product_mode_is_rejected_because_navigator_does_not_support_it(self):
        with patch("backend.control_plane._script", side_effect=lambda path: f"/repo/{path}"):
            with self.assertRaises(ControlPlaneError):
                build_operation({"kind": "scrape", "source": "daraz", "mode": "single", "url": "https://daraz.pk/products/example-i1.html"})

    def test_whatmobile_product_mode_is_rejected_because_navigator_is_catalog_based(self):
        with patch("backend.control_plane._script", side_effect=lambda path: f"/repo/{path}"):
            with self.assertRaises(ControlPlaneError):
                build_operation({"kind": "scrape", "source": "whatmobile", "mode": "single", "url": "https://www.whatmobile.com.pk/Example_Phone-1"})

    def test_server_secret_is_preferred_for_server_side_reads(self):
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SECRET_KEY": "sb_secret_server",
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_browser",
        }, clear=False):
            client = SupabaseREST()
            self.assertEqual(client._key(False), "sb_secret_server")

    def test_scraper_url_must_match_selected_source_domain(self):
        with patch("backend.control_plane._script", side_effect=lambda path: f"/repo/{path}"):
            with self.assertRaises(ControlPlaneError):
                build_operation({"kind": "scrape", "source": "mega", "mode": "single", "url": "https://example.com/not-mega"})

    def test_etl_sites_are_allowlisted(self):
        with patch("backend.control_plane._script", side_effect=lambda path: f"/repo/{path}"):
            with self.assertRaises(ControlPlaneError):
                build_operation({"kind": "organise", "sites": "gsmarena.com,evil.example"})

    def test_resume_upload_preserves_loader_state(self):
        with patch("backend.control_plane._script", side_effect=lambda path: f"/repo/{path}"):
            _kind, _label, command, _commands = build_operation({"kind": "upload-resume"})
        self.assertNotIn("--reset-state", command)
        self.assertNotIn("--allow-existing", command)

    def test_existing_database_preflight_uses_loader_replay_flags(self):
        with patch("backend.control_plane._script", side_effect=lambda path: f"/repo/{path}"):
            _kind, _label, command, _commands = build_operation({"kind": "upload-preflight", "allow_existing": True, "reset_state": True})
        self.assertIn("--preflight-only", command)
        self.assertIn("--allow-existing", command)
        self.assertIn("--reset-state", command)

    def test_etl_operation_is_blocked_while_another_job_is_active(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = JobManager(Path(temp_dir))
            manager._jobs["JOB-ACTIVE"] = Job(id="JOB-ACTIVE", kind="scrape", label="active", status="running")
            with self.assertRaises(ControlPlaneError):
                manager.submit(kind="convert", label="convert", command=[sys.executable, "-c", "pass"])

    def test_scrapers_can_overlap_each_other_but_not_exclusive_etl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = JobManager(Path(temp_dir))
            manager._jobs["JOB-ETL"] = Job(id="JOB-ETL", kind="upload", label="upload", status="running")
            with self.assertRaises(ControlPlaneError):
                manager.submit(kind="scrape", label="scrape", command=[sys.executable, "-c", "pass"])

    def test_new_supabase_keys_are_not_used_as_bearer_tokens(self):
        headers = SupabaseREST._headers("sb_secret_example", "analytics")
        self.assertEqual(headers["apikey"], "sb_secret_example")
        self.assertNotIn("Authorization", headers)


if __name__ == "__main__":
    unittest.main()
