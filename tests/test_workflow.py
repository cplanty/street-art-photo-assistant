import json
import tempfile
import unittest
from pathlib import Path
from shutil import copy2

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


if __name__ == "__main__":
    unittest.main()

