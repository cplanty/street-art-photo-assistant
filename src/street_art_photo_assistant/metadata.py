"""Previewed, atomic flat-keyword metadata edits."""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import piexif
from iptcinfo3 import IPTCInfo

from .change_log import write_change_log
from .models import FileFingerprint
from .photos import read_keywords

XPKEYWORDS_TAG = 0x9C9E


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


def _encode_xpkeywords(keywords: list[str]) -> bytes:
    return ";".join(keywords).encode("utf-16le") + b"\x00\x00"


def _write_keywords_in_place(path: Path, keywords: list[str]) -> None:
    info = IPTCInfo(str(path), force=True)
    info["keywords"] = [keyword.encode("utf-8") for keyword in keywords]
    info.save()
    backup = Path(str(path) + "~")
    if backup.exists():
        backup.unlink()

    exif = piexif.load(str(path))
    exif["0th"][XPKEYWORDS_TAG] = _encode_xpkeywords(keywords)
    piexif.insert(piexif.dump(exif), str(path))


def _atomic_keyword_write(path: Path, keywords: list[str]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    backup = Path(str(temporary) + "~")
    try:
        shutil.copy2(path, temporary)
        _write_keywords_in_place(temporary, keywords)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)


def build_tag_edit_plan(
    paths: Iterable[Path],
    *,
    add: Iterable[str] = (),
    remove: Iterable[str] = (),
) -> dict[str, Any]:
    """Build an exact no-write keyword edit preview."""

    additions = list(dict.fromkeys(tag.strip() for tag in add if tag.strip()))
    removals = list(dict.fromkeys(tag.strip() for tag in remove if tag.strip()))
    if not additions and not removals:
        raise ValueError("At least one tag addition or removal is required")
    remove_folded = {tag.casefold() for tag in removals}
    items = []
    for path in dict.fromkeys(Path(value).resolve() for value in paths):
        before = list(read_keywords(path))
        after = [tag for tag in before if tag.casefold() not in remove_folded]
        existing = {tag.casefold() for tag in after}
        for tag in additions:
            if tag.casefold() not in existing:
                after.append(tag)
                existing.add(tag.casefold())
        items.append({
            "path": str(path),
            "fingerprint": _fingerprint_dict(path),
            "before": before,
            "after": after,
            "changed": before != after,
        })
    return {
        "version": 1,
        "kind": "tag-edit",
        "id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "add": additions,
        "remove": removals,
        "items": items,
    }


def apply_tag_edit_plan(
    plan: dict[str, Any],
    *,
    allowed_roots: Iterable[Path],
    change_log_path: Path,
) -> int:
    """Preflight and apply exactly one previewed tag plan."""

    if (
        plan.get("version") != 1
        or plan.get("kind") != "tag-edit"
        or not isinstance(plan.get("items"), list)
    ):
        raise ValueError("Invalid tag edit plan")
    roots = tuple(Path(root).resolve() for root in allowed_roots)
    if not roots:
        raise ValueError("At least one allowed photo root is required")

    prepared = []
    for item in plan["items"]:
        path = Path(str(item.get("path") or "")).resolve()
        if not _inside_roots(path, roots):
            raise ValueError(f"Tag edit path is outside configured sources: {path}")
        if not path.is_file():
            raise ValueError(f"Tag edit target no longer exists: {path}")
        if _fingerprint_dict(path) != item.get("fingerprint"):
            raise ValueError(f"Tag edit target changed after preview: {path}")
        if list(read_keywords(path)) != item.get("before"):
            raise ValueError(f"Tag edit keywords changed after preview: {path}")
        prepared.append((path, item))

    changes = []
    for path, item in prepared:
        if not item.get("changed"):
            continue
        _atomic_keyword_write(path, list(item["after"]))
        changes.append({
            "file": str(path),
            "before": {"tags": item["before"]},
            "after": {"tags": item["after"]},
        })
        write_change_log(
            change_log_path,
            operation="tag-edit",
            plan_id=str(plan["id"]),
            changes=changes,
            status="applying",
        )
    write_change_log(
        change_log_path,
        operation="tag-edit",
        plan_id=str(plan["id"]),
        changes=changes,
        status="complete",
    )
    return len(changes)
