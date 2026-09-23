"""Application-level offline selection and clustering workflow."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import date, time
from pathlib import Path
from typing import Any

from .clustering import SelectionCriteria, cluster_photos, select_photos
from .matching import visual_subcluster
from .models import PhotoSource
from .photos import scan_sources
from .reporting import write_cluster_report


def _optional_date(value: object) -> date | None:
    text = str(value or "").strip()
    return date.fromisoformat(text) if text else None


def _optional_time(value: object) -> time | None:
    text = str(value or "").strip()
    return time.fromisoformat(text) if text else None


def _resolve(base: Path, value: object) -> Path:
    path = Path(str(value or "")).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    os.replace(temporary, path)


def sources_from_config(
    config: dict[str, Any],
    config_root: Path,
) -> list[PhotoSource]:
    """Resolve configured source paths against the configuration directory."""

    return [
        PhotoSource(
            name=str(item["name"]),
            path=_resolve(config_root, item["path"]),
            enabled=item.get("enabled", True) is not False,
            gps_target=bool(item.get("gps_target", False)),
            gps_reference=bool(item.get("gps_reference", False)),
        )
        for item in config["sources"]
    ]


def selection_from_config(config: dict[str, Any]) -> SelectionCriteria:
    """Build typed selection criteria from the JSON contract."""

    selection = config["selection"]
    return SelectionCriteria(
        start=_optional_date(selection.get("start")),
        end=_optional_date(selection.get("end")),
        start_time=_optional_time(selection.get("start_time")),
        end_time=_optional_time(selection.get("end_time")),
        tagged_mode=str(selection["tagged_mode"]),
        include_tags=tuple(selection.get("include_tags") or []),
        exclude_tags=tuple(selection.get("exclude_tags") or []),
        missing_gps=str(selection["missing_gps"]),
    )


def scan_and_select(
    config: dict[str, Any],
    config_root: Path,
) -> tuple[list, list, object]:
    """Scan configured sources and apply the exact configured selection."""

    scanned = scan_sources(sources_from_config(config, config_root))
    selected, preview = select_photos(
        scanned, selection_from_config(config)
    )
    return scanned, selected, preview


def run_offline_clustering(
    config: dict[str, Any],
    *,
    config_root: Path,
    output_directory: Path,
    visual: bool = False,
) -> dict[str, Any]:
    """Run the complete network-free preview and clustering workflow."""

    _scanned, selected, preview = scan_and_select(config, config_root)
    clustering = config["clustering"]
    clusters = cluster_photos(
        selected,
        radius_m=float(clustering["radius_m"]),
        generic_tags=clustering.get("generic_tags") or [],
        context_only_tags=clustering.get("context_only_tags") or [],
        unknown_tag=str(clustering["unknown_tag"]),
        wall_tag=str(clustering["wall_tag"]),
    )
    if visual:
        clusters = visual_subcluster(clusters)

    output_directory.mkdir(parents=True, exist_ok=True)
    _atomic_json(output_directory / "preview.json", asdict(preview))
    write_cluster_report(
        clusters,
        output_directory / "report.json",
        output_directory / "report.md",
    )
    return {
        "scanned": preview.scanned,
        "selected": preview.selected,
        "clusters": len(clusters),
        "output_directory": str(output_directory.resolve()),
    }
