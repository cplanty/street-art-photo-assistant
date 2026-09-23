import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from street_art_photo_assistant.models import FileFingerprint, PhotoRecord


class ModelTests(unittest.TestCase):
    def test_photo_record_serializes_paths_dates_and_tags(self):
        photo = PhotoRecord(
            path=Path("photo.jpg"),
            source="Camera",
            captured_at=datetime(2026, 1, 2, 3, 4, 5),
            latitude=48.0,
            longitude=2.0,
            tags=("Artist",),
        )

        payload = photo.to_dict()

        self.assertEqual("photo.jpg", payload["path"])
        self.assertEqual("2026-01-02T03:04:05", payload["captured_at"])
        self.assertEqual(["Artist"], payload["tags"])
        self.assertTrue(photo.has_gps)

    def test_file_fingerprint_changes_with_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "photo.jpg"
            path.write_bytes(b"one")
            before = FileFingerprint.from_path(path)
            path.write_bytes(b"two-more")
            after = FileFingerprint.from_path(path)

        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()

