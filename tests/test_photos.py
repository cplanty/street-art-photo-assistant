import tempfile
import unittest
from pathlib import Path
from shutil import copy2

from street_art_photo_assistant.models import PhotoSource
from street_art_photo_assistant.photos import discover_jpegs, read_photo, scan_sources


FIXTURES = Path(__file__).parent / "fixtures"


class PhotoTests(unittest.TestCase):
    def test_reads_capture_gps_dimensions_and_keywords(self):
        photo = read_photo(FIXTURES / "located.jpg", "Camera")

        self.assertEqual("2026-01-02T12:34:56", photo.captured_at.isoformat())
        self.assertAlmostEqual(48.0, photo.latitude, places=5)
        self.assertAlmostEqual(2.0, photo.longitude, places=5)
        self.assertEqual((32, 24), (photo.width, photo.height))
        self.assertIn("StreetArt", photo.tags)

    def test_missing_gps_remains_explicit(self):
        photo = read_photo(FIXTURES / "missing-gps.jpg", "Camera")
        self.assertFalse(photo.has_gps)

    def test_discovery_and_disabled_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            copy2(FIXTURES / "located.jpg", folder / "one.JPG")
            (folder / "ignore.txt").write_text("not a photo", encoding="utf-8")
            self.assertEqual(["one.JPG"], [p.name for p in discover_jpegs(folder)])
            records = scan_sources([
                PhotoSource("Enabled", folder),
                PhotoSource("Disabled", folder, enabled=False),
            ])
        self.assertEqual(1, len(records))
        self.assertEqual("Enabled", records[0].source)


if __name__ == "__main__":
    unittest.main()

