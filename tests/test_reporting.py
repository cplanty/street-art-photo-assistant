import json
import tempfile
import unittest
from pathlib import Path

from street_art_photo_assistant.models import PhotoCluster, PhotoRecord
from street_art_photo_assistant.reporting import write_cluster_report


class ReportingTests(unittest.TestCase):
    def test_writes_offline_json_and_markdown(self):
        cluster = PhotoCluster(
            id="abc",
            tag="_unknown",
            photos=[PhotoRecord(Path("one.jpg"), "Camera", None, None, None)],
        )
        with tempfile.TemporaryDirectory() as temporary:
            json_path = Path(temporary) / "report.json"
            markdown_path = Path(temporary) / "report.md"
            write_cluster_report([cluster], json_path, markdown_path)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")

        self.assertEqual("cluster-only", payload["mode"])
        self.assertEqual("_unknown", payload["clusters"][0]["tag"])
        self.assertIn("matching was disabled", markdown)


if __name__ == "__main__":
    unittest.main()

