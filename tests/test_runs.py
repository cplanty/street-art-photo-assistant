import sys
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from shutil import copy2

from street_art_photo_assistant.config import DEFAULT_CONFIG
from street_art_photo_assistant.runs import RunManager


FIXTURES = Path(__file__).parent / "fixtures"


class RunManagerTests(unittest.TestCase):
    def test_run_persists_report_summary_and_safe_delete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            photos = root / "photos"
            photos.mkdir()
            copy2(FIXTURES / "located.jpg", photos / "photo.jpg")
            config = deepcopy(DEFAULT_CONFIG)
            config["sources"] = [{
                "name": "Camera",
                "path": str(photos),
                "enabled": True,
            }]
            manager = RunManager(
                root / "runs", python_executable=Path(sys.executable)
            )
            run = manager.start(config)
            deadline = time.time() + 15
            while time.time() < deadline:
                run = manager.status(run["id"], include_log=True)
                if run["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.05)

            self.assertEqual("complete", run["status"], run.get("log"))
            self.assertEqual(1, run["selected_photos"])
            self.assertEqual(1, run["clusters"])
            self.assertEqual(1, len(manager.report(run["id"])["clusters"]))
            manager.delete(run["id"])
            self.assertEqual([], manager.list_runs())

    def test_invalid_run_id_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = RunManager(Path(temporary))
            with self.assertRaisesRegex(ValueError, "Invalid run id"):
                manager.status("..")


if __name__ == "__main__":
    unittest.main()

