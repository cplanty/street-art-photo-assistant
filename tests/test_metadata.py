import json
import tempfile
import unittest
from pathlib import Path
from shutil import copy2
from unittest.mock import patch

from street_art_photo_assistant.metadata import (
    apply_tag_edit_plan,
    build_tag_edit_plan,
)
from street_art_photo_assistant.photos import read_keywords


FIXTURES = Path(__file__).parent / "fixtures"


class MetadataTests(unittest.TestCase):
    def test_tag_plan_writes_both_flat_keyword_stores_and_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            photo = root / "photo.jpg"
            copy2(FIXTURES / "located.jpg", photo)
            plan = build_tag_edit_plan([photo], add=["Artist"])
            self.assertEqual(["StreetArt"], plan["items"][0]["before"])
            log = root / "change.json"

            changed = apply_tag_edit_plan(
                plan,
                allowed_roots=[root],
                change_log_path=log,
            )

            payload = json.loads(log.read_text(encoding="utf-8"))
            self.assertEqual(1, changed)
            self.assertEqual(("Artist", "StreetArt"), tuple(sorted(read_keywords(photo))))
            self.assertEqual("tag-edit", payload["operation"])

    def test_stale_plan_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            photo = root / "photo.jpg"
            copy2(FIXTURES / "located.jpg", photo)
            plan = build_tag_edit_plan([photo], add=["Artist"])
            photo.write_bytes(photo.read_bytes() + b"changed")

            with self.assertRaisesRegex(ValueError, "changed after preview"):
                apply_tag_edit_plan(
                    plan,
                    allowed_roots=[root],
                    change_log_path=root / "change.json",
                )

    def test_path_outside_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            allowed = root / "allowed"
            allowed.mkdir()
            photo = root / "photo.jpg"
            copy2(FIXTURES / "located.jpg", photo)
            plan = build_tag_edit_plan([photo], add=["Artist"])

            with self.assertRaisesRegex(ValueError, "outside configured"):
                apply_tag_edit_plan(
                    plan,
                    allowed_roots=[allowed],
                    change_log_path=root / "change.json",
                )

    def test_successful_writes_are_logged_before_a_later_write_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.jpg"
            second = root / "second.jpg"
            copy2(FIXTURES / "located.jpg", first)
            copy2(FIXTURES / "located.jpg", second)
            plan = build_tag_edit_plan([first, second], add=["Artist"])
            log = root / "change.json"

            from street_art_photo_assistant import metadata

            real_write = metadata._atomic_keyword_write
            calls = 0

            def fail_second(path, keywords):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("write failed")
                real_write(path, keywords)

            with patch.object(
                metadata, "_atomic_keyword_write", side_effect=fail_second
            ):
                with self.assertRaisesRegex(OSError, "write failed"):
                    apply_tag_edit_plan(
                        plan,
                        allowed_roots=[root],
                        change_log_path=log,
                    )

            payload = json.loads(log.read_text(encoding="utf-8"))
            self.assertEqual("applying", payload["status"])
            self.assertEqual([str(first)], [
                change["file"] for change in payload["changes"]
            ])


if __name__ == "__main__":
    unittest.main()
