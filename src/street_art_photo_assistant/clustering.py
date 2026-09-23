"""Photo selection preview and deterministic tag/location clustering."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from datetime import date, time
from typing import Iterable

from .models import PhotoCluster, PhotoRecord

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class SelectionCriteria:
    start: date | None = None
    end: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    tagged_mode: str = "both"
    include_tags: tuple[str, ...] = ()
    exclude_tags: tuple[str, ...] = ()
    missing_gps: str = "include"


@dataclass(frozen=True)
class SelectionPreview:
    scanned: int
    selected: int
    tagged: int
    untagged: int
    missing_gps: int
    first_capture: str | None
    last_capture: str | None
    sources: dict[str, int]
    tags: dict[str, int]


def haversine_m(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return great-circle distance in metres."""

    lat_a, lat_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    )
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _tag_set(values: Iterable[str]) -> set[str]:
    return {value.casefold() for value in values}


def select_photos(
    photos: Iterable[PhotoRecord],
    criteria: SelectionCriteria,
) -> tuple[list[PhotoRecord], SelectionPreview]:
    """Apply all source filters once and return a read-only preview."""

    if criteria.tagged_mode not in {"both", "tagged", "untagged"}:
        raise ValueError("tagged_mode is invalid")
    if criteria.missing_gps not in {"include", "exclude", "only"}:
        raise ValueError("missing_gps is invalid")
    include = _tag_set(criteria.include_tags)
    exclude = _tag_set(criteria.exclude_tags)
    scanned = list(photos)
    selected: list[PhotoRecord] = []

    for photo in scanned:
        tags = _tag_set(photo.tags)
        if criteria.start or criteria.end or criteria.start_time or criteria.end_time:
            if photo.captured_at is None:
                continue
            if criteria.start and photo.captured_at.date() < criteria.start:
                continue
            if criteria.end and photo.captured_at.date() > criteria.end:
                continue
            if criteria.start_time and photo.captured_at.time() < criteria.start_time:
                continue
            if criteria.end_time and photo.captured_at.time() > criteria.end_time:
                continue
        if criteria.tagged_mode == "tagged" and not tags:
            continue
        if criteria.tagged_mode == "untagged" and tags:
            continue
        if include and not tags.intersection(include):
            continue
        if tags.intersection(exclude):
            continue
        if criteria.missing_gps == "exclude" and not photo.has_gps:
            continue
        if criteria.missing_gps == "only" and photo.has_gps:
            continue
        selected.append(photo)

    captures = sorted(
        photo.captured_at for photo in selected if photo.captured_at is not None
    )
    source_counts = Counter(photo.source for photo in selected)
    tag_counts = Counter(tag for photo in selected for tag in photo.tags)
    preview = SelectionPreview(
        scanned=len(scanned),
        selected=len(selected),
        tagged=sum(bool(photo.tags) for photo in selected),
        untagged=sum(not photo.tags for photo in selected),
        missing_gps=sum(not photo.has_gps for photo in selected),
        first_capture=captures[0].isoformat() if captures else None,
        last_capture=captures[-1].isoformat() if captures else None,
        sources=dict(sorted(source_counts.items())),
        tags=dict(sorted(tag_counts.items(), key=lambda item: item[0].casefold())),
    )
    return selected, preview


def _identity_tags(
    photo: PhotoRecord,
    generic_tags: set[str],
    unknown_tag: str,
    wall_tag: str,
) -> list[str]:
    tags = [
        tag
        for tag in photo.tags
        if tag.casefold() not in generic_tags and not tag.startswith("_")
    ]
    if tags:
        return list(dict.fromkeys(tags))
    if any(tag.casefold() == wall_tag.casefold() for tag in photo.tags):
        return [wall_tag]
    return [unknown_tag]


def _centroid(photos: Iterable[PhotoRecord]) -> tuple[float | None, float | None]:
    located = [photo for photo in photos if photo.has_gps]
    if not located:
        return None, None
    return (
        sum(photo.latitude for photo in located if photo.latitude is not None)
        / len(located),
        sum(photo.longitude for photo in located if photo.longitude is not None)
        / len(located),
    )


def _cluster_id(tag: str, photos: Iterable[PhotoRecord]) -> str:
    material = tag + "\0" + "\0".join(
        sorted(str(photo.path).casefold() for photo in photos)
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _capture_sort_value(photo: PhotoRecord) -> float:
    if photo.captured_at is not None:
        return photo.captured_at.timestamp()
    try:
        return photo.path.stat().st_mtime
    except OSError:
        return 0.0


def cluster_photos(
    photos: Iterable[PhotoRecord],
    *,
    radius_m: float,
    generic_tags: Iterable[str] = (),
    context_only_tags: Iterable[str] = (),
    unknown_tag: str = "_unknown",
    wall_tag: str = "_wall",
) -> list[PhotoCluster]:
    """Group photos by identity tag and geographic proximity."""

    if radius_m <= 0:
        raise ValueError("radius_m must be positive")
    generic = _tag_set(generic_tags)
    context_only = _tag_set(context_only_tags)
    primary: list[tuple[PhotoRecord, str]] = []
    context: list[tuple[PhotoRecord, list[str]]] = []
    for photo in photos:
        identities = _identity_tags(photo, generic, unknown_tag, wall_tag)
        is_context = bool(_tag_set(photo.tags).intersection(context_only))
        if len(identities) > 1 or is_context:
            context.append((photo, identities))
        else:
            primary.append((photo, identities[0]))

    clusters: list[PhotoCluster] = []
    for photo, tag in sorted(
        primary,
        key=lambda item: (
            item[1].casefold(),
            _capture_sort_value(item[0]),
            str(item[0].path).casefold(),
        ),
    ):
        candidate = None
        if photo.has_gps:
            for cluster in reversed(clusters):
                if cluster.tag.casefold() != tag.casefold():
                    continue
                if cluster.latitude is None or cluster.longitude is None:
                    continue
                distance = haversine_m(
                    photo.latitude,
                    photo.longitude,
                    cluster.latitude,
                    cluster.longitude,
                )
                if distance <= radius_m:
                    candidate = cluster
                    break
        if candidate is None:
            candidate = PhotoCluster(id="", tag=tag)
            clusters.append(candidate)
        candidate.photos.append(photo)
        candidate.latitude, candidate.longitude = _centroid(candidate.photos)

    for photo, tags in context:
        nearest: tuple[float, PhotoCluster] | None = None
        if photo.has_gps:
            for cluster in clusters:
                if cluster.tag.casefold() not in _tag_set(tags):
                    continue
                if cluster.latitude is None or cluster.longitude is None:
                    continue
                distance = haversine_m(
                    photo.latitude,
                    photo.longitude,
                    cluster.latitude,
                    cluster.longitude,
                )
                if distance <= radius_m and (
                    nearest is None or distance < nearest[0]
                ):
                    nearest = (distance, cluster)
        if nearest is not None:
            nearest[1].context_photos.append(photo)
        else:
            tag = tags[0]
            cluster = PhotoCluster(
                id="",
                tag=tag,
                context_photos=[photo],
                latitude=photo.latitude,
                longitude=photo.longitude,
            )
            clusters.append(cluster)

    for cluster in clusters:
        cluster.id = _cluster_id(
            cluster.tag, [*cluster.photos, *cluster.context_photos]
        )
    return sorted(
        clusters,
        key=lambda cluster: (
            cluster.tag.casefold(),
            cluster.latitude is None,
            cluster.latitude or 0,
            cluster.longitude or 0,
            cluster.id,
        ),
    )
