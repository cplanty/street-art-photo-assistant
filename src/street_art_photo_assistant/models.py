"""Typed contracts shared by the local workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PhotoSource:
    """One reusable local photo source."""

    name: str
    path: Path
    enabled: bool = True
    gps_target: bool = False
    gps_reference: bool = False


@dataclass(frozen=True)
class PhotoRecord:
    """Normalized metadata used by selection, clustering, and editing."""

    path: Path
    source: str
    captured_at: datetime | None
    latitude: float | None
    longitude: float | None
    tags: tuple[str, ...] = ()
    width: int | None = None
    height: int | None = None

    @property
    def has_gps(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["path"] = str(self.path)
        result["captured_at"] = (
            self.captured_at.isoformat() if self.captured_at else None
        )
        result["tags"] = list(self.tags)
        return result


@dataclass
class PhotoCluster:
    """A reviewable group representing one probable artwork."""

    id: str
    tag: str
    photos: list[PhotoRecord] = field(default_factory=list)
    context_photos: list[PhotoRecord] = field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None
    visual_group: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tag": self.tag,
            "photos": [photo.to_dict() for photo in self.photos],
            "context_photos": [
                photo.to_dict() for photo in self.context_photos
            ],
            "latitude": self.latitude,
            "longitude": self.longitude,
            "visual_group": self.visual_group,
        }


@dataclass(frozen=True)
class FileFingerprint:
    """File identity used to reject stale metadata-write plans."""

    size: int
    modified_ns: int

    @classmethod
    def from_path(cls, path: Path) -> FileFingerprint:
        stat = path.stat()
        return cls(size=stat.st_size, modified_ns=stat.st_mtime_ns)


@dataclass(frozen=True)
class GPSRepairMatch:
    """One proposed missing-GPS repair."""

    target: Path
    reference: Path
    target_fingerprint: FileFingerprint
    reference_fingerprint: FileFingerprint
    latitude: float
    longitude: float
    time_difference_seconds: float


@dataclass
class GPSRepairPlan:
    """Persisted exact plan shown before GPS metadata is changed."""

    id: str
    created_at: datetime
    matches: list[GPSRepairMatch]


@dataclass
class RunManifest:
    """Persistent record of one selection/clustering/matching run."""

    id: str
    created_at: datetime
    status: str
    request: dict[str, Any]
    selected_photos: int = 0
    clusters: int = 0
    outputs: dict[str, str] = field(default_factory=dict)

