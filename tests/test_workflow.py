import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from shutil import copy2
from unittest.mock import patch

from street_art_photo_assistant.config import DEFAULT_CONFIG
from street_art_photo_assistant.workflow import run_offline_clustering


FIXTURES = Path(__file__).parent / "fixtures"


class WorkflowTests(unittest.TestCase):
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
        self.assertEqual(2, result["selected"])
        self.assertEqual(2, preview["selected"])
        self.assertEqual("cluster-only", report["mode"])

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
                    return_value={"city": "test-city", "markers": []},
                ) as refresh,
                patch(
                    "street_art_photo_assistant.sac.compare_clusters",
                    return_value=evidence,
                ) as compare,
            ):
                run_offline_clustering(
                    config,
                    config_root=root,
                    output_directory=root / "output",
                )
            report = json.loads(
                (root / "output" / "report.json").read_text(encoding="utf-8")
            )

        refresh.assert_called_once()
        compare.assert_called_once()
        self.assertEqual("street-art-cities", report["mode"])
        self.assertEqual("test-city", report["city"])


if __name__ == "__main__":
    unittest.main()
