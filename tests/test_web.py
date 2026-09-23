import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from shutil import copy2

from street_art_photo_assistant.config import DEFAULT_CONFIG
from street_art_photo_assistant.photos import read_photo
from street_art_photo_assistant.runs import RunManager
from street_art_photo_assistant.web import create_app


FIXTURES = Path(__file__).parent / "fixtures"


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.photos = self.root / "photos"
        self.photos.mkdir()
        self.located = self.photos / "located.jpg"
        self.missing = self.photos / "missing.jpg"
        copy2(FIXTURES / "located.jpg", self.located)
        copy2(FIXTURES / "missing-gps.jpg", self.missing)
        self.config = deepcopy(DEFAULT_CONFIG)
        self.config["sources"] = [{
            "name": "Camera",
            "path": str(self.photos),
            "enabled": True,
            "gps_target": True,
            "gps_reference": True,
        }]
        self.config_path = self.root / "config.local.json"
        self.manager = RunManager(self.root / "runs")
        self.app = create_app(
            self.config,
            self.config_path,
            run_manager=self.manager,
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    def preview(self):
        response = self.client.post("/api/preview", json=self.config)
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        return response.get_json()

    def test_health_and_generator_structure(self):
        self.assertEqual(
            {"status": "ok"}, self.client.get("/health").get_json()
        )
        response = self.client.get("/")
        self.assertEqual(200, response.status_code)
        page = response.get_data(as_text=True)
        self.assertIn("Street Art Cities matching", page)
        self.assertIn("Visual matching", page)
        self.assertIn("Configuration", page)
        self.assertIn("Preview selection", page)
        self.assertIn("Apply previewed GPS fixes", page)
        self.assertIn("Refresh &amp; run", page)

    def test_cached_cities_are_suggested(self):
        cache = self.root / "data" / "cities"
        cache.mkdir(parents=True)
        (cache / "test-city.json").write_text("{}", encoding="utf-8")
        response = self.client.get("/")
        self.assertIn(
            '<option value="test-city">',
            response.get_data(as_text=True),
        )

    def test_reference_route_is_confined_to_configured_cache(self):
        cache = self.root / "data" / "ref_images"
        cache.mkdir(parents=True)
        reference = cache / "marker.jpg"
        reference.write_bytes(b"synthetic")

        response = self.client.get("/reference", query_string={
            "path": str(reference),
        })
        self.assertEqual(200, response.status_code)
        response.close()
        self.assertEqual(
            404,
            self.client.get("/reference", query_string={
                "path": str(self.located),
            }).status_code,
        )

    def test_complete_config_is_saved(self):
        self.config["run_label"] = "Synthetic test"
        response = self.client.post("/api/config", json=self.config)
        self.assertEqual(200, response.status_code)
        self.assertIn("Synthetic test", self.config_path.read_text(encoding="utf-8"))

    def test_preview_gates_and_applies_same_source_gps_plan(self):
        preview = self.preview()
        self.assertEqual(2, preview["preview"]["selected"])
        response = self.client.post("/api/gps/preview", json={
            "config": self.config,
            "preview_token": preview["token"],
            "target_sources": ["Camera"],
            "reference_sources": ["Camera"],
        })
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        plan = response.get_json()["plan"]
        self.assertEqual(1, sum(
            item["status"] == "repairable" for item in plan["items"]
        ))

        applied = self.client.post(f"/api/plans/{plan['id']}/apply", json={})
        self.assertEqual(200, applied.status_code, applied.get_data(as_text=True))
        self.assertTrue(read_photo(self.missing, "Camera").has_gps)

    def test_run_can_be_opened_and_deleted(self):
        preview = self.preview()
        started = self.client.post("/api/runs", json={
            "config": self.config,
            "preview_token": preview["token"],
        }).get_json()["run"]
        deadline = time.time() + 15
        while time.time() < deadline:
            status = self.client.get(f"/api/runs/{started['id']}").get_json()["run"]
            if status["status"] not in {"queued", "running"}:
                break
            time.sleep(0.05)

        self.assertEqual("complete", status["status"], status.get("log"))
        self.assertEqual(200, self.client.get(f"/runs/{started['id']}").status_code)
        report = self.manager.report(started["id"])
        cluster_id = report["clusters"][0]["id"]
        self.assertEqual(
            200,
            self.client.get(
                f"/runs/{started['id']}/clusters/{cluster_id}"
            ).status_code,
        )
        deleted = self.client.delete(f"/api/runs/{started['id']}")
        self.assertEqual(200, deleted.status_code)
        self.assertEqual([], self.manager.list_runs())

    def test_changed_config_invalidates_preview_token(self):
        preview = self.preview()
        changed = deepcopy(self.config)
        changed["selection"]["tagged_mode"] = "tagged"
        response = self.client.post("/api/runs", json={
            "config": changed,
            "preview_token": preview["token"],
        })
        self.assertEqual(400, response.status_code)
        self.assertIn("unchanged", response.get_json()["error"])

    def test_read_only_mode_rejects_plan_apply(self):
        read_only = deepcopy(self.config)
        read_only["read_only"] = True
        app = create_app(
            read_only,
            self.config_path,
            run_manager=self.manager,
        )
        client = app.test_client()
        preview = client.post("/api/preview", json=read_only).get_json()
        plan = client.post("/api/gps/preview", json={
            "config": read_only,
            "preview_token": preview["token"],
            "target_sources": ["Camera"],
            "reference_sources": ["Camera"],
        }).get_json()["plan"]

        response = client.post(f"/api/plans/{plan['id']}/apply", json={})

        self.assertEqual(403, response.status_code)
        self.assertFalse(read_photo(self.missing, "Camera").has_gps)


if __name__ == "__main__":
    unittest.main()
