"""JPEG discovery and normalized metadata reading."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from iptcinfo3 import IPTCInfo
from PIL import Image
from PIL.ExifTags import IFD

from .models import PhotoRecord, PhotoSource

JPEG_SUFFIXES = {".jpg", ".jpeg"}
DATETIME_FORMAT = "%Y:%m:%d %H:%M:%S"


def discover_jpegs(folder: Path) -> list[Path]:
    """Return JPEG paths recursively in deterministic order."""

    if not folder.is_dir():
        raise ValueError(f"Photo source does not exist: {folder}")
    return sorted(
        (
            path
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.casefold() in JPEG_SUFFIXES
        ),
        key=lambda path: str(path).casefold(),
    )


def _decode_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00 ")
    return str(value or "").strip()


def decode_xpkeywords(value: object) -> list[str]:
    """Decode Windows XPKeywords into flat keyword values."""

    if value is None:
        return []
    if isinstance(value, tuple):
        value = bytes(value)
    if isinstance(value, bytes):
        text = value.decode("utf-16le", errors="ignore").rstrip("\x00")
    else:
        text = str(value)
    return [part.strip() for part in text.split(";") if part.strip()]


def _coordinate(values: Iterable[object], reference: object) -> float:
    degrees, minutes, seconds = (float(value) for value in values)
    result = degrees + minutes / 60 + seconds / 3600
    if _decode_text(reference).upper() in {"S", "W"}:
        result = -result
    return result


def _read_iptc_keywords(path: Path) -> list[str]:
    info = IPTCInfo(str(path), force=True)
    raw = info["keywords"] or []
    if not isinstance(raw, list):
        raw = [raw]
    return [_decode_text(value) for value in raw if _decode_text(value)]


def read_keywords(path: Path) -> tuple[str, ...]:
    """Merge flat IPTC and Windows keywords while preserving order."""

    with Image.open(path) as image:
        keywords = decode_xpkeywords(image.getexif().get(0x9C9E))
    try:
        keywords = [*_read_iptc_keywords(path), *keywords]
    except (OSError, TypeError, ValueError):
        pass
    return tuple(dict.fromkeys(tag for tag in keywords if tag))


def read_photo(path: Path, source: str) -> PhotoRecord:
    """Read one JPEG into the normalized public photo contract."""

    try:
        with Image.open(path) as image:
            width, height = image.size
            exif = image.getexif()
            exif_ifd = exif.get_ifd(IFD.Exif)
            captured_text = _decode_text(
                exif_ifd.get(0x9003) or exif.get(0x0132)
            )
            captured_at = (
                datetime.strptime(captured_text, DATETIME_FORMAT)
                if captured_text
                else None
            )
            gps = exif.get_ifd(IFD.GPSInfo)
            latitude = longitude = None
            if gps.get(2) and gps.get(4):
                latitude = _coordinate(gps[2], gps.get(1))
                longitude = _coordinate(gps[4], gps.get(3))
    except (OSError, SyntaxError, TypeError, ValueError) as exc:
        raise ValueError(f"Could not read photo metadata: {path}") from exc

    try:
        tags = read_keywords(path)
    except (OSError, SyntaxError, TypeError, ValueError) as exc:
        raise ValueError(f"Could not read photo keywords: {path}") from exc
    return PhotoRecord(
        path=path.resolve(),
        source=source,
        captured_at=captured_at,
        latitude=latitude,
        longitude=longitude,
        tags=tags,
        width=width,
        height=height,
    )


def scan_sources(sources: Iterable[PhotoSource]) -> list[PhotoRecord]:
    """Scan enabled sources and fail explicitly on unreadable photos."""

    records: list[PhotoRecord] = []
    for source in sources:
        if not source.enabled:
            continue
        for path in discover_jpegs(source.path):
            records.append(read_photo(path, source.name))
    return records
