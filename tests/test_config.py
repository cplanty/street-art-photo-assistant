import json
import tempfile
import unittest
from pathlib import Path

from street_art_photo_assistant.config import load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_missing_file_loads_safe_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(Path(temporary) / "missing.json")

        self.assertEqual("_unknown", config["clustering"]["unknown_tag"])
        self.assertEqual("_wall", config["clustering"]["wall_tag"])
        self.assertFalse(config["matching"]["street_art_cities_enabled"])
        self.assertFalse(config["matching"]["download_images"])
        self.assertEqual([], config["selection"]["exclude_tags"])

    def test_save_round_trip_is_atomic_and_utf8(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.local.json"
            config = load_config(path)
            config["sources"] = [{
                "name": "Téléphone",
                "path": r"C:\Photos",
                "enabled": True,
            }]
            save_config(path, config)
            loaded = load_config(path)

        self.assertEqual(config, loaded)

    def test_invalid_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.local.json"
            path.write_text(json.dumps({
                "version": 1,
                "selection": {"tagged_mode": "invalid"},
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "tagged_mode"):
                load_config(path)

    def test_enabled_matching_requires_a_safe_city_slug(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.local.json"
            path.write_text(json.dumps({
                "version": 1,
                "matching": {
                    "street_art_cities_enabled": True,
                    "city": "../Example",
                },
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lowercase slug"):
                load_config(path)

    def test_request_interval_cannot_be_negative(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.local.json"
            path.write_text(json.dumps({
                "version": 1,
                "matching": {"request_interval_seconds": -1},
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cannot be negative"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
