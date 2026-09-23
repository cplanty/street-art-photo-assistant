"""Deterministic missing-GPS and manual-position plans."""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import piexif

from .change_log import write_change_log
from .models import FileFingerprint, PhotoRecord
from .photos import read_photo


def _fingerprint_dict(path: Path) -> dict[str, int]:
    fingerprint = FileFingerprint.from_path(path)
    return {
        "size": fingerprint.size,
        "modified_ns": fingerprint.modified_ns,
    }


def _inside_roots(path: Path, allowed_roots: Iterable[Path]) -> bool:
    resolved = path.resolve()
    return any(
        resolved == root.resolve() or resolved.is_relative_to(root.resolve())
        for root in allowed_roots
    )


def _dms(value: float) -> tuple[tuple[int, int], ...]:
    absolute = abs(value)
    degrees = int(absolute)
    minutes_float = (absolute - degrees) * 60
    minutes = int(minutes_float)
    seconds = round((minutes_float - minutes) * 60 * 1_000_000)
    return ((degrees, 1), (minutes, 1), (seconds, 1_000_000))


def _write_gps_in_place(path: Path, latitude: float, longitude: float) -> None:
    exif = piexif.load(str(path))
    exif["GPS"][piexif.GPSIFD.GPSLatitudeRef] = (
        b"S" if latitude < 0 else b"N"
    )
    exif["GPS"][piexif.GPSIFD.GPSLatitude] = _dms(latitude)
    exif["GPS"][piexif.GPSIFD.GPSLongitudeRef] = (
        b"W" if longitude < 0 else b"E"
    )
    exif["GPS"][piexif.GPSIFD.GPSLongitude] = _dms(longitude)
    piexif.insert(piexif.dump(exif), str(path))


def _atomic_gps_write(path: Path, latitude: float, longitude: float) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(path, temporary)
        _write_gps_in_place(temporary, latitude, longitude)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_missing_gps_plan(
    targets: Iterable[PhotoRecord],
    references: Iterable[PhotoRecord],
    *,
    maximum_time_difference_seconds: int,
    target_sources: Iterable[str] = (),
    reference_sources: Iterable[str] = (),
) -> dict[str, Any]:
    """Match selected missing-GPS targets to nearest trusted capture times."""

    if maximum_time_difference_seconds <= 0:
        raise ValueError("maximum_time_difference_seconds must be positive")
    target_names = set(target_sources)
    reference_names = set(reference_sources)
    eligible_targets = [
        photo
        for photo in targets
        if not photo.has_gps
        and (not target_names or photo.source in target_names)
    ]
    eligible_references = [
        photo
        for photo in references
        if photo.has_gps
        and (not reference_names or photo.source in reference_names)
        and photo.captured_at is not None
    ]
    items = []
    for target in eligible_targets:
        item: dict[str, Any] = {
            "target": str(target.path.resolve()),
            "target_source": target.source,
            "target_fingerprint": _fingerprint_dict(target.path),
            "status": "unmatched",
        }
        if target.captured_at is None:
            item["status"] = "no-capture-time"
            items.append(item)
            continue
        candidates = [
            (
                abs((reference.captured_at - target.captured_at).total_seconds()),
                reference,
            )
            for reference in eligible_references
            if reference.path.resolve() != target.path.resolve()
        ]
        candidates = [
            candidate
            for candidate in candidates
            if candidate[0] <= maximum_time_difference_seconds
        ]
        if candidates:
            difference, reference = min(
                candidates,
                key=lambda candidate: (
                    candidate[0],
                    str(candidate[1].path).casefold(),
                ),
            )
            item.update({
                "status": "repairable",
                "reference": str(reference.path.resolve()),
                "reference_source": reference.source,
                "reference_fingerprint": _fingerprint_dict(reference.path),
                "reference_latitude": reference.latitude,
                "reference_longitude": reference.longitude,
                "time_difference_seconds": difference,
            })
        items.append(item)
    return {
        "version": 1,
        "kind": "missing-gps",
        "id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "maximum_time_difference_seconds": maximum_time_difference_seconds,
        "target_sources": sorted(target_names),
        "reference_sources": sorted(reference_names),
        "items": items,
    }


def build_manual_gps_plan(
    photos: Iterable[PhotoRecord],
    *,
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    """Build an explicit preview for manually assigning one position."""

    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("GPS position is out of range")
    return {
        "version": 1,
        "kind": "manual-gps",
        "id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "items": [
            {
                "path": str(photo.path.resolve()),
                "fingerprint": _fingerprint_dict(photo.path),
                "before": {
                    "latitude": photo.latitude,
                    "longitude": photo.longitude,
                },
                "after": {"latitude": latitude, "longitude": longitude},
            }
            for photo in photos
        ],
    }


def build_individual_gps_plan(
    moves: Iterable[tuple[PhotoRecord, float, float]],
) -> dict[str, Any]:
    """Build one exact plan containing independent photo positions."""

    items = []
    for photo, latitude, longitude in moves:
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("GPS position is out of range")
        items.append({
            "path": str(photo.path.resolve()),
            "fingerprint": _fingerprint_dict(photo.path),
            "before": {
                "latitude": photo.latitude,
                "longitude": photo.longitude,
            },
            "after": {"latitude": latitude, "longitude": longitude},
        })
    if not items:
        raise ValueError("Select at least one GPS move")
    return {
        "version": 1,
        "kind": "manual-gps",
        "id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }


def apply_gps_plan(
    plan: dict[str, Any],
    *,
    allowed_roots: Iterable[Path],
    change_log_path: Path,
) -> int:
    """Preflight and apply an exact missing or manual GPS plan."""

    if plan.get("version") != 1 or plan.get("kind") not in {
        "missing-gps",
        "manual-gps",
    } or not isinstance(plan.get("items"), list):
        raise ValueError("Invalid GPS plan")
    roots = tuple(Path(root).resolve() for root in allowed_roots)
    if not roots:
        raise ValueError("At least one allowed photo root is required")

    prepared = []
    for item in plan["items"]:
        if plan["kind"] == "missing-gps" and item.get("status") != "repairable":
            continue
        path_key = "target" if plan["kind"] == "missing-gps" else "path"
        fingerprint_key = (
            "target_fingerprint"
            if plan["kind"] == "missing-gps"
            else "fingerprint"
        )
        path = Path(str(item.get(path_key) or "")).resolve()
        if not _inside_roots(path, roots):
            raise ValueError(f"GPS target is outside configured sources: {path}")
        if not path.is_file():
            raise ValueError(f"GPS target no longer exists: {path}")
        if _fingerprint_dict(path) != item.get(fingerprint_key):
            raise ValueError(f"GPS target changed after preview: {path}")
        current = read_photo(path, "")
        if plan["kind"] == "missing-gps":
            if current.has_gps:
                raise ValueError(f"GPS target gained coordinates: {path}")
            reference = Path(str(item.get("reference") or "")).resolve()
            if not _inside_roots(reference, roots) or not reference.is_file():
                raise ValueError(f"GPS reference is unavailable: {reference}")
            if _fingerprint_dict(reference) != item.get("reference_fingerprint"):
                raise ValueError(
                    f"GPS reference changed after preview: {reference}"
                )
            reference_photo = read_photo(reference, "")
            if (
                reference_photo.latitude != item.get("reference_latitude")
                or reference_photo.longitude != item.get("reference_longitude")
            ):
                raise ValueError(
                    f"GPS reference coordinates changed: {reference}"
                )
            after = {
                "latitude": item["reference_latitude"],
                "longitude": item["reference_longitude"],
            }
            before = {"latitude": None, "longitude": None}
        else:
            before = item["before"]
            current_position = {
                "latitude": current.latitude,
                "longitude": current.longitude,
            }
            if current_position != before:
                raise ValueError(f"GPS target coordinates changed: {path}")
            after = item["after"]
        prepared.append((path, before, after))

    changes = []
    for path, before, after in prepared:
        _atomic_gps_write(path, after["latitude"], after["longitude"])
        changes.append({"file": str(path), "before": before, "after": after})
        write_change_log(
            change_log_path,
            operation=str(plan["kind"]),
            plan_id=str(plan["id"]),
            changes=changes,
            status="applying",
        )
    write_change_log(
        change_log_path,
        operation=str(plan["kind"]),
        plan_id=str(plan["id"]),
        changes=changes,
        status="complete",
    )
    return len(changes)
