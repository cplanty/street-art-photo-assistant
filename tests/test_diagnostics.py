import tempfile
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path

from street_art_photo_assistant.config import DEFAULT_CONFIG
from street_art_photo_assistant.diagnostics import create_diagnostic_bundle


class DiagnosticTests(unittest.TestCase):
    def test_detailed_bundle_redacts_paths_and_excludes_private_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_root = root / "runs"
            run_id = "2026-01-02_120000_abcd1234"
            run_path = run_root / run_id
            run_path.mkdir(parents=True)
            private_photo = root / "private photos" / "secret.jpg"
            config = deepcopy(DEFAULT_CONFIG)
            config["sources"] = [{
                "name": "Private Camera",
                "path": str(private_photo.parent),
                "enabled": True,
            }]
            config["selection"]["include_tags"] = ["Private Artist"]
            (run_path / "run.log").write_text(
                f"Failed reading {private_photo}\n"
                "Contact private@example.test\n",
                encoding="utf-8",
            )
            (run_path / "report.json").write_text(
                '{"latitude":48.123,"longitude":2.456}',
                encoding="utf-8",
            )
            app_log = run_root / "_logs" / "app.jsonl"
            app_log.parent.mkdir()
            app_log.write_text(
                f'{{"message":"{private_photo}"}}\n',
                encoding="utf-8",
            )
            runs = [{
                "id": run_id,
                "status": "failed",
                "stage": "clustering",
                "error": f"Could not read {private_photo}",
                "selected_photos": None,
                "clusters": None,
            }]

            bundle = create_diagnostic_bundle(
                config=config,
                run_root=run_root,
                runs=runs,
                detailed=True,
            )
            with zipfile.ZipFile(bundle) as archive:
                names = set(archive.namelist())
                combined = "\n".join(
                    archive.read(name).decode("utf-8") for name in names
                )

        self.assertIn("bundle-manifest.json", names)
        self.assertIn(f"run-logs/{run_id}.log", names)
        self.assertNotIn("report.json", names)
        self.assertNotIn(str(private_photo), combined)
        self.assertNotIn("private@example.test", combined)
        self.assertNotIn("Private Artist", combined)
        self.assertNotIn("48.123", combined)
        self.assertIn("<LOCAL_PATH", combined)
        self.assertIn("<EMAIL>", combined)

    def test_safe_bundle_does_not_include_run_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = create_diagnostic_bundle(
                config=deepcopy(DEFAULT_CONFIG),
                run_root=root,
                runs=[],
                detailed=False,
            )
            with zipfile.ZipFile(bundle) as archive:
                names = archive.namelist()

        self.assertFalse(any(name.startswith("run-logs/") for name in names))


if __name__ == "__main__":
    unittest.main()
