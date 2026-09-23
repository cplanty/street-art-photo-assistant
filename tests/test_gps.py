import json
import tempfile
import unittest
from pathlib import Path
from shutil import copy2

from street_art_photo_assistant.gps import (
    apply_gps_plan,
    build_individual_gps_plan,
    build_manual_gps_plan,
    build_missing_gps_plan,
)
from street_art_photo_assistant.photos import read_photo


FIXTURES = Path(__file__).parent / "fixtures"


class GPSTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.target_path = self.root / "missing.jpg"
        self.reference_path = self.root / "located.jpg"
        copy2(FIXTURES / "missing-gps.jpg", self.target_path)
        copy2(FIXTURES / "located.jpg", self.reference_path)

    def tearDown(self):
        self.temporary.cleanup()

    def test_same_camera_missing_gps_preview_and_apply(self):
        target = read_photo(self.target_path, "Camera")
        reference = read_photo(self.reference_path, "Camera")
        plan = build_missing_gps_plan(
            [target],
            [target, reference],
            maximum_time_difference_seconds=300,
            target_sources=["Camera"],
            reference_sources=["Camera"],
        )
        self.assertEqual("repairable", plan["items"][0]["status"])
        log = self.root / "change.json"

        changed = apply_gps_plan(
            plan,
            allowed_roots=[self.root],
            change_log_path=log,
        )

        repaired = read_photo(self.target_path, "Camera")
        payload = json.loads(log.read_text(encoding="utf-8"))
        self.assertEqual(1, changed)
        self.assertAlmostEqual(48.0, repaired.latitude, places=5)
        self.assertEqual("missing-gps", payload["operation"])

    def test_cross_camera_roles_are_honored(self):
        target = read_photo(self.target_path, "Camera A")
        reference = read_photo(self.reference_path, "Camera B")
        plan = build_missing_gps_plan(
            [target],
            [reference],
            maximum_time_difference_seconds=300,
            target_sources=["Camera A"],
            reference_sources=["Camera B"],
        )
        self.assertEqual("Camera B", plan["items"][0]["reference_source"])

    def test_changed_reference_rejects_whole_plan(self):
        target = read_photo(self.target_path, "Camera A")
        reference = read_photo(self.reference_path, "Camera B")
        plan = build_missing_gps_plan(
            [target],
            [reference],
            maximum_time_difference_seconds=300,
        )
        self.reference_path.write_bytes(
            self.reference_path.read_bytes() + b"changed"
        )

        with self.assertRaisesRegex(ValueError, "reference changed"):
            apply_gps_plan(
                plan,
                allowed_roots=[self.root],
                change_log_path=self.root / "change.json",
            )
        self.assertFalse(read_photo(self.target_path, "Camera A").has_gps)

    def test_manual_plan_can_explicitly_move_existing_gps(self):
        original = read_photo(self.reference_path, "Camera")
        plan = build_manual_gps_plan(
            [original],
            latitude=47.5,
            longitude=1.5,
        )

        changed = apply_gps_plan(
            plan,
            allowed_roots=[self.root],
            change_log_path=self.root / "manual.json",
        )

        moved = read_photo(self.reference_path, "Camera")
        self.assertEqual(1, changed)
        self.assertAlmostEqual(47.5, moved.latitude, places=5)
        self.assertAlmostEqual(1.5, moved.longitude, places=5)

    def test_individual_plan_keeps_distinct_positions(self):
        first = read_photo(self.reference_path, "Camera")
        second_path = self.root / "located-2.jpg"
        copy2(FIXTURES / "located.jpg", second_path)
        second = read_photo(second_path, "Camera")
        plan = build_individual_gps_plan([
            (first, 47.5, 1.5),
            (second, 47.6, 1.6),
        ])

        changed = apply_gps_plan(
            plan,
            allowed_roots=[self.root],
            change_log_path=self.root / "individual.json",
        )

        self.assertEqual(2, changed)
        self.assertAlmostEqual(
            47.5, read_photo(self.reference_path, "Camera").latitude, places=5
        )
        self.assertAlmostEqual(
            47.6, read_photo(second_path, "Camera").latitude, places=5
        )


if __name__ == "__main__":
    unittest.main()
