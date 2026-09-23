"""Privacy-aware local diagnostic bundles for issue reports."""

from __future__ import annotations

import json
import platform
import re
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterable

from . import __version__

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
WINDOWS_PATH_RE = re.compile(
    r"(?<![\w])(?:[A-Za-z]:\\|\\\\)[^\r\n\t\"'<>|]+"
)
MAX_LOG_CHARS = 200_000


def _redact_text(value: str, sensitive_paths: Iterable[Path]) -> str:
    text = value
    replacements = sorted(
        {
            str(path.expanduser().resolve())
            for path in sensitive_paths
            if str(path)
        },
        key=len,
        reverse=True,
    )
    for index, path in enumerate(replacements, start=1):
        text = text.replace(path, f"<LOCAL_PATH_{index}>")
        text = text.replace(path.replace("\\", "/"), f"<LOCAL_PATH_{index}>")
    text = EMAIL_RE.sub("<EMAIL>", text)
    return WINDOWS_PATH_RE.sub("<LOCAL_PATH>", text)


def _config_summary(config: dict[str, Any]) -> dict[str, Any]:
    selection = config["selection"]
    matching = config["matching"]
    return {
        "version": config["version"],
        "source_count": len(config["sources"]),
        "sources": [
            {
                "id": f"SOURCE_{index}",
                "enabled": source.get("enabled", True),
                "gps_target": bool(source.get("gps_target")),
                "gps_reference": bool(source.get("gps_reference")),
            }
            for index, source in enumerate(config["sources"], start=1)
        ],
        "selection": {
            "has_start": bool(selection.get("start")),
            "has_end": bool(selection.get("end")),
            "has_time_filter": bool(
                selection.get("start_time") or selection.get("end_time")
            ),
            "tagged_mode": selection.get("tagged_mode"),
            "include_tag_count": len(selection.get("include_tags") or []),
            "exclude_tag_count": len(selection.get("exclude_tags") or []),
            "missing_gps": selection.get("missing_gps"),
        },
        "clustering": {
            "radius_m": config["clustering"].get("radius_m"),
            "generic_tag_count": len(
                config["clustering"].get("generic_tags") or []
            ),
            "context_only_tag_count": len(
                config["clustering"].get("context_only_tags") or []
            ),
        },
        "gps_repair": {
            "maximum_time_difference_seconds": config["gps_repair"].get(
                "maximum_time_difference_seconds"
            ),
        },
        "matching": {
            "street_art_cities_enabled": bool(
                matching.get("street_art_cities_enabled")
            ),
            "city_configured": bool(matching.get("city")),
            "visual_enabled": bool(matching.get("visual_enabled")),
            "download_images": bool(matching.get("download_images")),
            "profile": matching.get("profile"),
            "candidate_radius_m": matching.get("candidate_radius_m"),
            "request_interval_seconds": matching.get(
                "request_interval_seconds"
            ),
            "large_city_warning_markers": matching.get(
                "large_city_warning_markers"
            ),
            "large_reference_warning": matching.get(
                "large_reference_warning"
            ),
        },
        "read_only": bool(config.get("read_only")),
    }


def _environment() -> dict[str, Any]:
    packages = {}
    for package in (
        "Flask",
        "Pillow",
        "piexif",
        "iptcinfo3",
        "requests",
        "numpy",
        "opencv-python",
    ):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    return {
        "application": "Street Art Photo Assistant",
        "application_version": __version__,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "operating_system": platform.system(),
        "operating_system_release": platform.release(),
        "machine": platform.machine(),
        "packages": packages,
    }


def _run_summaries(
    runs: list[dict[str, Any]],
    sensitive_paths: Iterable[Path],
) -> list[dict[str, Any]]:
    summaries = []
    for run in runs[:10]:
        error = str(run.get("error") or "")
        summaries.append({
            "id": run.get("id"),
            "created_at": run.get("created_at"),
            "updated_at": run.get("updated_at"),
            "status": run.get("status"),
            "stage": run.get("stage"),
            "visual": bool(run.get("visual")),
            "selected_photos": run.get("selected_photos"),
            "clusters": run.get("clusters"),
            "error": (
                _redact_text(error, sensitive_paths) if error else None
            ),
        })
    return summaries


def create_diagnostic_bundle(
    *,
    config: dict[str, Any],
    run_root: Path,
    runs: list[dict[str, Any]],
    detailed: bool = False,
) -> Path:
    """Create an inspectable ZIP that excludes photos and raw report data."""

    run_root = run_root.resolve()
    diagnostic_root = run_root / "_diagnostics"
    diagnostic_root.mkdir(parents=True, exist_ok=True)
    sensitive_paths = [
        run_root,
        *[
            Path(str(source.get("path") or ""))
            for source in config["sources"]
            if source.get("path")
        ],
        *[
            Path(str(path))
            for path in config.get("paths", {}).values()
            if path
        ],
    ]
    identifier = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "_"
        + uuid.uuid4().hex[:8]
    )
    output = diagnostic_root / f"diagnostics_{identifier}.zip"
    files: dict[str, str] = {
        "environment.json": json.dumps(
            _environment(), indent=2, ensure_ascii=False
        ) + "\n",
        "config-summary.json": json.dumps(
            _config_summary(config), indent=2, ensure_ascii=False
        ) + "\n",
        "runs.json": json.dumps(
            _run_summaries(runs, sensitive_paths),
            indent=2,
            ensure_ascii=False,
        ) + "\n",
    }
    app_log = run_root / "_logs" / "app.jsonl"
    if app_log.is_file():
        text = app_log.read_text(encoding="utf-8", errors="replace")
        files["app-log.jsonl"] = _redact_text(
            text[-MAX_LOG_CHARS:], sensitive_paths
        )
    if detailed:
        for run in runs[:3]:
            run_id = str(run.get("id") or "")
            if not run_id or Path(run_id).name != run_id:
                continue
            log_path = run_root / run_id / "run.log"
            if log_path.is_file() and log_path.is_relative_to(run_root):
                text = log_path.read_text(
                    encoding="utf-8", errors="replace"
                )
                files[f"run-logs/{run_id}.log"] = _redact_text(
                    text[-MAX_LOG_CHARS:], sensitive_paths
                )
    notice = {
        "level": "detailed" if detailed else "safe",
        "included": sorted(files),
        "excluded": [
            "photos and thumbnails",
            "raw configuration",
            "cluster reports and GPS coordinates",
            "artist mappings and reference caches",
            "metadata edit plans and change logs",
        ],
        "review_before_sharing": True,
    }
    files["bundle-manifest.json"] = json.dumps(
        notice, indent=2, ensure_ascii=False
    ) + "\n"
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output
