import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from shutil import copy2
from unittest.mock import patch

from street_art_photo_assistant.config import DEFAULT_CONFIG
from street_art_photo_assistant.workflow import (
    ProgressReporter,
    run_offline_clustering,
)


FIXTURES = Path(__file__).parent / "fixtures"


class WorkflowTests(unittest.TestCase):
    def test_progress_write_retries_windows_sharing_violation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "progress.json"
            original_replace = os.replace
            calls = 0

            def flaky_replace(source, destination):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise PermissionError("temporarily locked")
                original_replace(source, destination)

            with (
                patch(
                    "street_art_photo_assistant.workflow.os.replace",
                    side_effect=flaky_replace,
                ),
                patch("street_art_photo_assistant.workflow.sleep"),
            ):
                ProgressReporter(path).update(
                    stage="test",
                    percent=1,
                    message="Testing",
                )

            self.assertEqual(2, calls)
            self.assertEqual("test", json.loads(
                path.read_text(encoding="utf-8")
            )["stage"])

    def test_offline_workflow_writes_preview_and_reports(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            photos = root / "photos"
            photos.mkdir()
            copy2(FIXTURES / "located.jpg", photos / "located.jpg")
            copy2(FIXTURES / "missing-gps.jpg", photos / "missing.jpg")
            config = {
                **DEFAULT_CONFIG,
                "sources": [{
                    "name": "Camera",
                    "path": "photos",
                    "enabled": True,
                }],
            }
            output = root / "output"

            result = run_offline_clustering(
                config,
                config_root=root,
                output_directory=output,
            )

            preview = json.loads(
                (output / "preview.json").read_text(encoding="utf-8")
            )
            report = json.loads(
                (output / "report.json").read_text(encoding="utf-8")
            )
            progress = json.loads(
                (output / "progress.json").read_text(encoding="utf-8")
            )
        self.assertEqual(2, result["selected"])
        self.assertEqual(2, preview["selected"])
        self.assertEqual("cluster-only", report["mode"])
        self.assertEqual(100, progress["percent"])
        self.assertEqual("complete", progress["stage"])

    def test_enabled_matching_refreshes_city_and_adds_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            photos = root / "photos"
            photos.mkdir()
            copy2(FIXTURES / "located.jpg", photos / "located.jpg")
            config = deepcopy(DEFAULT_CONFIG)
            config["sources"] = [{
                "name": "Camera",
                "path": "photos",
                "enabled": True,
            }]
            config["matching"]["street_art_cities_enabled"] = True
            config["matching"]["city"] = "test-city"
            config["matching"]["download_images"] = True
            config["matching"]["large_city_warning_markers"] = 1
            evidence = {
                "synthetic": {
                    "status": "likely-new",
                    "recommendation": "No nearby marker",
                    "candidates": [],
                }
            }
            with (
                patch(
                    "street_art_photo_assistant.sac.refresh_city",
                    return_value={
                        "city": "test-city",
                        "markers": [{"image_url": "https://example.test/a.jpg"}],
                    },
                ) as refresh,
                patch(
                    "street_art_photo_assistant.sac.compare_clusters",
                    return_value=evidence,
                ) as compare,
                patch(
                    "street_art_photo_assistant.sac.cache_city_images",
                    return_value={
                        "available": 1,
                        "cached": 1,
                        "failed": 0,
                    },
                ) as cache_images,
            ):
                run_offline_clustering(
                    config,
                    config_root=root,
                    output_directory=root / "output",
                )
            report = json.loads(
                (root / "output" / "report.json").read_text(encoding="utf-8")
            )
            progress = json.loads(
                (root / "output" / "progress.json").read_text(encoding="utf-8")
            )

        refresh.assert_called_once()
        compare.assert_called_once()
        cache_images.assert_called_once()
        self.assertEqual("street-art-cities", report["mode"])
        self.assertEqual("test-city", report["city"])
        self.assertIn("Large city catalogue", progress["warnings"][0])

    def test_authenticated_marker_source_uses_environment_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            photos = root / "photos"
            photos.mkdir()
            copy2(FIXTURES / "located.jpg", photos / "located.jpg")
            config = deepcopy(DEFAULT_CONFIG)
            config["sources"] = [{
                "name": "Camera",
                "path": "photos",
                "enabled": True,
            }]
            config["matching"]["street_art_cities_enabled"] = True
            config["matching"]["marker_source"] = "oauth-markers-api"
            config["matching"]["city"] = "test-city"
            with (
                patch.dict(
                    os.environ,
                    {"SAC_API_ACCESS_TOKEN": "test-access-token"},
                ),
                patch(
                    "street_art_photo_assistant.sac.refresh_city_api",
                    return_value={
                        "city": "test-city",
                        "source": "oauth-markers-api",
                        "markers": [],
                    },
                ) as refresh,
                patch(
                    "street_art_photo_assistant.sac.compare_clusters",
                    return_value={},
                ),
            ):
                run_offline_clustering(
                    config,
                    config_root=root,
                    output_directory=root / "output",
                )

        refresh.assert_called_once()
        self.assertEqual(
            "test-access-token",
            refresh.call_args.kwargs["access_token"],
        )


if __name__ == "__main__":
    unittest.main()
