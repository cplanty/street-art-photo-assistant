import json
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from shutil import copy2
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from street_art_photo_assistant.config import DEFAULT_CONFIG
from street_art_photo_assistant.photos import read_photo
from street_art_photo_assistant.runs import RunManager
from street_art_photo_assistant.web import _choose_folder, create_app


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

    def test_native_folder_picker_is_parented_and_topmost(self):
        root = Mock()
        with (
            patch("tkinter.Tk", return_value=root),
            patch(
                "tkinter.filedialog.askdirectory",
                return_value=str(self.photos),
            ) as askdirectory,
        ):
            selected = _choose_folder(str(self.photos))

        self.assertEqual(str(self.photos), selected)
        root.attributes.assert_called_once_with("-topmost", True)
        askdirectory.assert_called_once()
        self.assertIs(root, askdirectory.call_args.kwargs["parent"])

    def test_health_and_generator_structure(self):
        self.assertEqual(
            {"status": "ok"}, self.client.get("/health").get_json()
        )
        response = self.client.get("/")
        self.assertEqual(200, response.status_code)
        page = response.get_data(as_text=True)
        self.assertIn("Street Art Cities matching", page)
        self.assertIn("Public city snapshot (established)", page)
        self.assertIn("OAuth Markers API (new)", page)
        self.assertIn('href="/login"', page)
        self.assertIn("not connected", page)
        self.assertIn(
            "const loginUrl = event.currentTarget.href;",
            page,
        )
        self.assertIn("window.location.assign(loginUrl);", page)
        self.assertIn("Visual matching", page)
        self.assertIn("Cache all SAC city pictures", page)
        self.assertIn("Configuration", page)
        self.assertIn("Preview selection", page)
        self.assertIn("Last 24h", page)
        self.assertIn("setLast24Hours", page)
        self.assertIn("Apply previewed GPS fixes", page)
        self.assertIn("Refresh &amp; run", page)
        self.assertIn('id="run-cancel-button"', page)
        self.assertIn("cancelCurrentRun", page)
        self.assertIn('id="run-progress"', page)
        self.assertIn('id="recent-runs-body"', page)
        self.assertIn("refreshRecentRuns", page)
        self.assertIn("Generate diagnostic package", page)
        self.assertIn(
            "Preview complete. You can now generate report",
            page,
        )
        self.assertNotIn('id="temporary_folder" readonly', page)
        self.assertNotIn('readonly placeholder="Choose a folder"', page)

    def test_generator_restores_newest_active_run_after_refresh(self):
        with patch.object(
            self.manager,
            "list_runs",
            return_value=[{
                "id": "newest-running",
                "label": "",
                "status": "running",
                "selected_photos": None,
                "clusters": None,
            }, {
                "id": "older-running",
                "label": "",
                "status": "running",
                "selected_photos": None,
                "clusters": None,
            }],
        ):
            page = self.client.get("/").get_data(as_text=True)

        self.assertIn('let currentRun = "newest-running";', page)
        self.assertIn("Restoring active run", page)
        self.assertIn("if (currentRun)", page)

    def test_generates_local_redacted_diagnostic_bundle(self):
        response = self.client.post(
            "/api/diagnostics", json={"detailed": False}
        )

        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual("safe", payload["level"])
        bundle = Path(payload["path"])
        self.assertTrue(bundle.is_file())
        self.assertTrue(
            bundle.is_relative_to(self.manager.run_root / "_diagnostics")
        )

    def test_cached_cities_are_suggested(self):
        cache = self.root / "data" / "cities"
        cache.mkdir(parents=True)
        (cache / "test-city.json").write_text("{}", encoding="utf-8")
        response = self.client.get("/")
        self.assertIn(
            '<option value="test-city">',
            response.get_data(as_text=True),
        )

    def test_pkce_login_callback_and_collections_probe(self):
        self.config["matching"]["api_client_id"] = "sac_client_test"
        saved = self.client.post("/api/config", json=self.config)
        self.assertEqual(200, saved.status_code)

        started = self.client.get("/login")
        self.assertEqual(302, started.status_code)
        authorization = urlparse(started.headers["Location"])
        query = parse_qs(authorization.query)
        self.assertEqual("streetartcities.com", authorization.netloc)
        self.assertEqual(
            ["collections:read markers:read"], query["scope"]
        )
        self.assertEqual(["S256"], query["code_challenge_method"])

        with patch(
            "street_art_photo_assistant.web.exchange_pkce_code",
            return_value={
                "access_token": "test-access-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "collections:read markers:read",
            },
        ) as exchange:
            callback = self.client.get("/login", query_string={
                "code": "one-use-code",
                "state": query["state"][0],
            })
        self.assertEqual(200, callback.status_code)
        self.assertIn("Connected.", callback.get_data(as_text=True))
        exchange.assert_called_once()
        self.assertNotIn(
            "test-access-token", callback.get_data(as_text=True)
        )
        home = self.client.get("/").get_data(as_text=True)
        self.assertIn(
            "connected with <code>collections:read markers:read</code>",
            home,
        )
        self.assertIn("Disconnect local session", home)
        self.assertIn("Authorize again", home)

        with patch(
            "street_art_photo_assistant.web.fetch_collections",
            return_value=[{"id": "collection-1"}],
        ) as fetch:
            response = self.client.get("/api/sac/collections")
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            [{"id": "collection-1"}],
            response.get_json()["collections"],
        )
        fetch.assert_called_once_with("test-access-token")

        api_config = deepcopy(self.config)
        api_config["matching"]["street_art_cities_enabled"] = True
        api_config["matching"]["marker_source"] = "oauth-markers-api"
        api_config["matching"]["city"] = "test-city"
        self.client.post("/api/config", json=api_config)
        preview = self.client.post(
            "/api/preview", json=api_config
        ).get_json()
        with patch.object(
            self.manager,
            "start",
            return_value={"id": "test-run", "status": "queued"},
        ) as start:
            started = self.client.post("/api/runs", json={
                "config": api_config,
                "preview_token": preview["token"],
            })
        self.assertEqual(200, started.status_code)
        self.assertEqual(
            {"SAC_API_ACCESS_TOKEN": "test-access-token"},
            start.call_args.kwargs["environment"],
        )

        disconnected = self.client.post("/api/sac/disconnect", json={})
        self.assertEqual(200, disconnected.status_code)
        self.assertEqual(
            401, self.client.get("/api/sac/collections").status_code
        )

    def test_pkce_callback_rejects_unknown_state(self):
        response = self.client.get("/login", query_string={
            "code": "one-use-code",
            "state": "unknown",
        })

        self.assertEqual(400, response.status_code)
        self.assertIn("state", response.get_data(as_text=True))

    def test_authenticated_marker_run_requires_connection(self):
        config = deepcopy(self.config)
        config["matching"]["street_art_cities_enabled"] = True
        config["matching"]["marker_source"] = "oauth-markers-api"
        config["matching"]["city"] = "test-city"
        preview = self.client.post("/api/preview", json=config).get_json()

        response = self.client.post("/api/runs", json={
            "config": config,
            "preview_token": preview["token"],
        })

        self.assertEqual(400, response.status_code)
        self.assertIn("Connect", response.get_json()["error"])

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

    def test_new_public_artist_can_be_added_once(self):
        response = self.client.post("/api/artists", json={
            "tag": "New Artist",
            "slug": "new-artist",
            "instagram": "@new.artist",
        })

        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        self.assertTrue(response.get_json()["added"])
        artists = self.root / "data" / "artists.csv"
        self.assertIn(
            "New Artist;new-artist;new.artist;confirmed",
            artists.read_text(encoding="utf-8"),
        )
        duplicate = self.client.post("/api/artists", json={
            "tag": "new artist",
            "slug": "new-artist",
            "instagram": "new.artist",
        })
        self.assertFalse(duplicate.get_json()["added"])

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
        self.assertEqual(100, status["progress"]["percent"])
        self.assertEqual("complete", status["progress"]["stage"])
        dashboard = self.client.get(f"/runs/{started['id']}")
        self.assertEqual(200, dashboard.status_code)
        dashboard_page = dashboard.get_data(as_text=True)
        self.assertIn("Cluster dashboard", dashboard_page)
        self.assertIn('class="cluster-table"', dashboard_page)
        self.assertIn("Capture time", dashboard_page)
        self.assertIn("SAC status", dashboard_page)
        sorted_dashboard = self.client.get(
            f"/runs/{started['id']}?sort=time&dir=desc"
        )
        self.assertIn(
            "sort=time&amp;dir=asc",
            sorted_dashboard.get_data(as_text=True),
        )
        report = self.manager.report(started["id"])
        cluster_id = report["clusters"][0]["id"]
        artists = self.root / "data" / "artists.csv"
        artists.parent.mkdir(parents=True, exist_ok=True)
        artists.write_text(
            "tag;streetartcities_slug;instagram;status\n"
            "Test Artist;test-artist;test.artist;confirmed\n",
            encoding="utf-8",
        )
        report["clusters"][0]["street_art_cities"] = {
            "status": "review",
            "recommendation": "Review nearby marker",
            "candidates": [{
                "marker_id": "marker-1",
                "url": "https://streetartcities.com/markers/marker-1",
                "title": "Test marker",
                "artist": "Test Artist",
                "artist_slug": "test-artist",
                "latitude": 48.0,
                "longitude": 2.0,
                "distance_m": 12,
                "status": "active",
                "tag_match": True,
                "cached_image": None,
            }],
        }
        (self.manager.run_root / started["id"] / "report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
        detail = self.client.get(
            f"/runs/{started['id']}/clusters/{cluster_id}"
        )
        self.assertEqual(200, detail.status_code)
        detail_page = detail.get_data(as_text=True)
        self.assertIn('id="detail-view"', detail_page)
        self.assertIn('id="gps-map"', detail_page)
        self.assertIn('/static/leaflet.js', detail_page)
        self.assertNotIn("unpkg.com", detail_page)
        self.assertIn("Offline coordinate grid", detail_page)
        self.assertIn("Add to all", detail_page)
        self.assertIn("Add to selected", detail_page)
        self.assertIn("Show in Explorer", detail_page)
        self.assertIn("On all photos:", detail_page)
        self.assertIn("_unknown", detail_page)
        self.assertIn("_wall", detail_page)
        self.assertLess(
            detail_page.index('<option value="_unknown">'),
            detail_page.index('<option value="_wall">'),
        )
        self.assertIn("event.ctrlKey", detail_page)
        self.assertIn("ArrowLeft", detail_page)
        self.assertIn("ArrowRight", detail_page)
        self.assertIn("applyIndividualGpsMoves", detail_page)
        self.assertNotIn("Preview individual moves", detail_page)
        self.assertIn("Apply to all", detail_page)
        self.assertIn("Google Maps", detail_page)
        self.assertIn("Street View", detail_page)
        self.assertIn("sac-status-active", detail_page)
        self.assertIn("SAC artist", detail_page)
        self.assertIn("Instagram", detail_page)
        self.assertIn(
            "https://streetartcities.com/artists/test-artist",
            detail_page,
        )
        self.assertIn("https://www.instagram.com/test.artist/", detail_page)
        self.assertIn('id="artist-csv-dialog"', detail_page)
        self.assertIn("maybeAddArtistToCsv", detail_page)
        self.assertIn("applyTagChange", detail_page)
        self.assertNotIn("previewTagChange", detail_page)
        self.assertNotIn("Apply previewed tags", detail_page)
        self.assertIn("event.key !== 'Enter'", detail_page)
        self.assertIn("requestAnimationFrame", detail_page)
        self.assertIn("Satellite + labels", detail_page)
        self.assertIn("Topographic (OpenTopoMap)", detail_page)
        self.assertIn("Light (CARTO)", detail_page)
        self.assertIn('id="gps-readout"', detail_page)
        self.assertNotIn('<input id="latitude"', detail_page)
        self.assertNotIn("moveTargetFromFields", detail_page)
        self.assertIn("marker${moved.length === 1 ? '' : 's'} moved (not saved yet)", detail_page)
        self.assertIn("resetAllGps", detail_page)
        self.assertIn("gps-popup-thumbnail", detail_page)
        stylesheet_response = self.client.get("/static/app.css")
        stylesheet = stylesheet_response.get_data(as_text=True)
        self.assertIn("[hidden] { display: none !important; }", stylesheet)
        self.assertIn(".sac-status-active { color: #1a7f37; }", stylesheet)
        self.assertIn(".sac-status-removed { color: #cf222e; }", stylesheet)
        stylesheet_response.close()
        listed = self.client.get("/api/runs").get_json()["runs"]
        self.assertEqual(started["id"], listed[0]["id"])
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

    def test_changed_run_label_keeps_preview_token_valid(self):
        preview = self.preview()
        changed = deepcopy(self.config)
        changed["run_label"] = "Label added after preview"

        response = self.client.post("/api/runs", json={
            "config": changed,
            "preview_token": preview["token"],
        })

        self.assertEqual(200, response.status_code)
        run = response.get_json()["run"]
        self.assertEqual(
            "Label added after preview",
            run["label"],
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            if self.manager.status(run["id"])["status"] not in {
                "queued", "running"
            }:
                break
            time.sleep(0.05)

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

    def test_cluster_tag_preview_accepts_only_selected_cluster_photos(self):
        preview = self.preview()
        started = self.client.post("/api/runs", json={
            "config": self.config,
            "preview_token": preview["token"],
        }).get_json()["run"]
        deadline = time.time() + 15
        while time.time() < deadline:
            status = self.manager.status(started["id"])
            if status["status"] not in {"queued", "running"}:
                break
            time.sleep(0.05)
        report = self.manager.report(started["id"])
        cluster = report["clusters"][0]
        photo_path = cluster["photos"][0]["path"]
        endpoint = (
            f"/api/runs/{started['id']}/clusters/{cluster['id']}/tags/preview"
        )

        response = self.client.post(endpoint, json={
            "paths": [photo_path],
            "add": ["Synthetic Artist"],
            "remove": [],
        })
        self.assertEqual(200, response.status_code)
        self.assertEqual(1, len(response.get_json()["plan"]["items"]))

        rejected = self.client.post(endpoint, json={
            "paths": [str(self.root / "outside.jpg")],
            "add": ["Synthetic Artist"],
            "remove": [],
        })
        self.assertEqual(400, rejected.status_code)
        self.assertIn("outside this cluster", rejected.get_json()["error"])

    def test_cluster_individual_gps_preview_keeps_each_position(self):
        preview = self.preview()
        started = self.client.post("/api/runs", json={
            "config": self.config,
            "preview_token": preview["token"],
        }).get_json()["run"]
        deadline = time.time() + 15
        while time.time() < deadline:
            status = self.manager.status(started["id"])
            if status["status"] not in {"queued", "running"}:
                break
            time.sleep(0.05)
        cluster = self.manager.report(started["id"])["clusters"][0]
        photos = [*cluster["photos"], *cluster["context_photos"]]
        moves = [
            {
                "path": photo["path"],
                "latitude": 47.0 + index / 10,
                "longitude": 1.0 + index / 10,
            }
            for index, photo in enumerate(photos)
        ]

        response = self.client.post(
            f"/api/runs/{started['id']}/clusters/{cluster['id']}/gps/preview",
            json={"moves": moves},
        )

        self.assertEqual(200, response.status_code)
        items = response.get_json()["plan"]["items"]
        self.assertEqual(len(moves), len(items))
        self.assertEqual(
            [move["latitude"] for move in moves],
            [item["after"]["latitude"] for item in items],
        )

    def test_local_explorer_action_is_confined_to_photo_sources(self):
        with patch(
            "street_art_photo_assistant.web.subprocess.Popen"
        ) as popen:
            response = self.client.post("/api/open-local", json={
                "action": "explorer",
                "target": str(self.located),
            })
        self.assertEqual(200, response.status_code)
        popen.assert_called_once()

        rejected = self.client.post("/api/open-local", json={
            "action": "explorer",
            "target": str(self.root / "outside.jpg"),
        })
        self.assertEqual(400, rejected.status_code)


if __name__ == "__main__":
    unittest.main()
