"""Versioned local JSON configuration."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "auto_save": True,
    "sources": [],
    "temporary_folder": "_tmp_photos",
    "selection": {
        "start": "",
        "end": "",
        "start_time": "",
        "end_time": "",
        "tagged_mode": "both",
        "include_tags": [],
        "exclude_tags": [],
        "missing_gps": "include",
    },
    "clustering": {
        "radius_m": 35,
        "unknown_tag": "_unknown",
        "wall_tag": "_wall",
        "generic_tags": ["StreetArt", "Stickers"],
        "context_only_tags": [],
    },
    "gps_repair": {"maximum_time_difference_seconds": 300},
    "matching": {
        "street_art_cities_enabled": False,
        "city": "",
        "profile": "balanced",
        "candidate_radius_m": 80,
    },
    "paths": {"artists": "data/artists.csv", "runs": "_runs"},
    "read_only": False,
}


def _merge(defaults: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(defaults)
    for key, value in values.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def validate_config(config: dict[str, Any]) -> None:
    """Validate structure needed before the application starts."""

    if config.get("version") != 1:
        raise ValueError("Unsupported configuration version")
    if not isinstance(config.get("sources"), list):
        raise ValueError("sources must be a list")
    for index, source in enumerate(config["sources"]):
        if not isinstance(source, dict):
            raise ValueError(f"sources[{index}] must be an object")
        if not str(source.get("name") or "").strip():
            raise ValueError(f"sources[{index}].name is required")
        if not str(source.get("path") or "").strip():
            raise ValueError(f"sources[{index}].path is required")
    selection = config.get("selection", {})
    if selection.get("tagged_mode") not in {"both", "tagged", "untagged"}:
        raise ValueError("selection.tagged_mode is invalid")
    if selection.get("missing_gps") not in {"include", "exclude", "only"}:
        raise ValueError("selection.missing_gps is invalid")
    if float(config["clustering"]["radius_m"]) <= 0:
        raise ValueError("clustering.radius_m must be positive")
    if int(config["gps_repair"]["maximum_time_difference_seconds"]) <= 0:
        raise ValueError(
            "gps_repair.maximum_time_difference_seconds must be positive"
        )


def load_config(path: Path) -> dict[str, Any]:
    """Load and merge a local config, or return documented defaults."""

    if not path.exists():
        config = deepcopy(DEFAULT_CONFIG)
    else:
        with path.open(encoding="utf-8") as stream:
            raw = json.load(stream)
        if not isinstance(raw, dict):
            raise ValueError("Configuration must be a JSON object")
        config = _merge(DEFAULT_CONFIG, raw)
    validate_config(config)
    return config


def save_config(path: Path, config: dict[str, Any]) -> None:
    """Atomically save a validated local configuration."""

    validate_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(config, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    os.replace(temporary, path)


def resolve_local_path(project_root: Path, value: str) -> Path:
    """Resolve a configured path without depending on the process cwd."""

    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()

