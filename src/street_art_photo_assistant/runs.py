"""Persistent, cancellable offline clustering runs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    os.replace(temporary, path)


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


class RunManager:
    """Start and monitor reproducible package subprocesses."""

    def __init__(
        self,
        run_root: Path,
        *,
        python_executable: Path | None = None,
    ) -> None:
        self.run_root = run_root.resolve()
        self.python = Path(python_executable or sys.executable).resolve()
        self.run_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._cancelled: set[str] = set()

    def _run_path(self, run_id: str) -> Path:
        if (
            not run_id
            or run_id in {".", ".."}
            or Path(run_id).name != run_id
        ):
            raise ValueError("Invalid run id")
        path = (self.run_root / run_id).resolve()
        if not path.is_relative_to(self.run_root):
            raise ValueError("Run path escapes the run root")
        return path

    def _manifest_path(self, run_id: str) -> Path:
        return self._run_path(run_id) / "manifest.json"

    def _write_manifest(self, manifest: dict[str, Any]) -> None:
        _atomic_json(self._manifest_path(str(manifest["id"])), manifest)

    def start(
        self,
        config: dict[str, Any],
        *,
        visual: bool = False,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        identifier = uuid.uuid4().hex[:8]
        run_id = f"{now.strftime('%Y-%m-%d_%H%M%S')}_{identifier}"
        run_path = self._run_path(run_id)
        run_path.mkdir(parents=True)
        config_path = run_path / "config.json"
        _atomic_json(config_path, config)
        command = [
            str(self.python),
            "-m",
            "street_art_photo_assistant",
            "cluster",
            "--config",
            str(config_path),
            "--output",
            str(run_path),
        ]
        if visual:
            command.append("--visual")
        manifest = {
            "version": 1,
            "id": run_id,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "status": "queued",
            "stage": "queued",
            "label": str(config.get("run_label") or ""),
            "visual": visual,
            "command": command,
            "selected_photos": None,
            "clusters": None,
            "outputs": {
                "preview": str(run_path / "preview.json"),
                "json": str(run_path / "report.json"),
                "markdown": str(run_path / "report.md"),
                "log": str(run_path / "run.log"),
            },
        }
        self._write_manifest(manifest)
        thread = threading.Thread(
            target=self._execute,
            args=(run_id, command),
            daemon=True,
            name=f"photo-run-{run_id}",
        )
        thread.start()
        return manifest

    def _execute(self, run_id: str, command: list[str]) -> None:
        with self._lock:
            if run_id in self._cancelled:
                self._cancelled.discard(run_id)
                return
        manifest = self.status(run_id)
        manifest.update({
            "status": "running",
            "stage": "clustering",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        self._write_manifest(manifest)
        log_path = self._run_path(run_id) / "run.log"
        try:
            with log_path.open("w", encoding="utf-8", newline="\n") as log:
                process = subprocess.Popen(
                    command,
                    cwd=self._run_path(run_id),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    shell=False,
                )
                with self._lock:
                    self._processes[run_id] = process
                    cancelled = run_id in self._cancelled
                if cancelled:
                    process.terminate()
                return_code = process.wait()
        except OSError as exc:
            manifest = self.status(run_id)
            manifest.update({
                "status": "failed",
                "stage": "failed",
                "error": str(exc),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            self._write_manifest(manifest)
            return
        finally:
            with self._lock:
                self._processes.pop(run_id, None)
                self._cancelled.discard(run_id)

        manifest = self.status(run_id)
        if manifest.get("status") == "cancelled":
            return
        if return_code != 0:
            manifest.update({
                "status": "failed",
                "stage": "failed",
                "error": f"Cluster command exited with code {return_code}",
            })
        else:
            try:
                preview = _load_json(self._run_path(run_id) / "preview.json")
                report = _load_json(self._run_path(run_id) / "report.json")
                manifest.update({
                    "status": "complete",
                    "stage": "complete",
                    "selected_photos": preview["selected"],
                    "clusters": len(report["clusters"]),
                })
            except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                manifest.update({
                    "status": "failed",
                    "stage": "failed",
                    "error": f"Run output is invalid: {exc}",
                })
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_manifest(manifest)

    def status(self, run_id: str, *, include_log: bool = False) -> dict[str, Any]:
        path = self._manifest_path(run_id)
        if not path.is_file():
            raise ValueError(f"Unknown run: {run_id}")
        manifest = _load_json(path)
        if include_log:
            log_path = self._run_path(run_id) / "run.log"
            manifest["log"] = (
                log_path.read_text(encoding="utf-8", errors="replace")
                if log_path.is_file()
                else ""
            )
        return manifest

    def list_runs(self) -> list[dict[str, Any]]:
        runs = []
        for path in self.run_root.iterdir():
            manifest = path / "manifest.json"
            if path.is_dir() and manifest.is_file():
                try:
                    runs.append(_load_json(manifest))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
        return sorted(
            runs,
            key=lambda run: str(run.get("created_at") or ""),
            reverse=True,
        )

    def cancel(self, run_id: str) -> dict[str, Any]:
        manifest = self.status(run_id)
        if manifest["status"] not in {"queued", "running"}:
            raise ValueError("Only queued or running runs can be cancelled")
        with self._lock:
            self._cancelled.add(run_id)
            process = self._processes.get(run_id)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        manifest.update({
            "status": "cancelled",
            "stage": "cancelled",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        self._write_manifest(manifest)
        return manifest

    def delete(self, run_id: str) -> None:
        manifest = self.status(run_id)
        if manifest["status"] in {"queued", "running"}:
            raise ValueError("An active run cannot be deleted")
        path = self._run_path(run_id)
        shutil.rmtree(path)

    def report(self, run_id: str) -> dict[str, Any]:
        manifest = self.status(run_id)
        if manifest["status"] != "complete":
            raise ValueError("Run is not complete")
        return _load_json(self._run_path(run_id) / "report.json")
