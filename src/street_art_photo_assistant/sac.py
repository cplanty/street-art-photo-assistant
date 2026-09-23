"""Optional Street Art Cities public-data adapter."""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image

from .clustering import haversine_m
from .matching import image_similarity
from .models import PhotoCluster

BASE_URL = "https://streetartcities.com"
MARKERS_URL = BASE_URL + "/data/cities/{city}/markers.json"
CITY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
USER_AGENT = "StreetArtPhotoAssistant/0.1 (+local community tool)"
PROFILE_LIMITS = {"quick": 4, "balanced": 8, "thorough": 16}


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    os.replace(temporary, path)


def _normalize_marker(item: dict[str, Any]) -> dict[str, Any]:
    location = item.get("location") or {}
    images = item.get("images") or []
    image_urls = []
    for image in images:
        if not isinstance(image, dict):
            continue
        url = image.get("url") or (image.get("sizes") or {}).get("large")
        if url and url not in image_urls:
            image_urls.append(str(url))
    if not image_urls and item.get("thumbnail"):
        image_urls.append(str(item["thumbnail"]))
    artists = item.get("artists") or []
    artist_slug = (
        str(artists[0].get("slug") or "") if artists else ""
    )
    href = str(item.get("href") or "")
    return {
        "marker_id": str(item.get("id") or ""),
        "url": urljoin(BASE_URL, href),
        "title": item.get("title"),
        "artist": item.get("artistsString"),
        "artist_slug": artist_slug,
        "latitude": location.get("lat"),
        "longitude": location.get("lng"),
        "address": location.get("address"),
        "image_url": image_urls[0] if image_urls else None,
        "status": item.get("status"),
    }


def refresh_city(
    city: str,
    cache_directory: Path,
    *,
    timeout_seconds: int = 90,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Refresh one complete city marker cache with a single bounded request."""

    city = city.strip().lower()
    if not CITY_RE.fullmatch(city):
        raise ValueError("City must be a lowercase slug")
    client = session or requests.Session()
    response = client.get(
        MARKERS_URL.format(city=city),
        headers={"User-Agent": USER_AGENT},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    raw = response.json()
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("Street Art Cities marker response has no items list")
    markers = [
        _normalize_marker(item)
        for item in items
        if isinstance(item, dict)
        and item.get("type") == "artwork"
        and item.get("id")
    ]
    payload = {
        "version": 1,
        "city": city,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "markers": markers,
    }
    _atomic_json(cache_directory / f"{city}.json", payload)
    return payload


def cached_cities(cache_directory: Path) -> list[str]:
    """List valid locally cached city slugs."""

    if not cache_directory.is_dir():
        return []
    return sorted(
        path.stem
        for path in cache_directory.glob("*.json")
        if CITY_RE.fullmatch(path.stem)
    )


def load_artist_mapping(path: Path) -> dict[str, str]:
    """Load accent-preserving, case-insensitive local tag-to-slug mappings."""

    mapping = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            tag = str(row.get("tag") or "").strip()
            slug = str(row.get("streetartcities_slug") or "").strip()
            if tag and slug:
                mapping[tag.casefold()] = slug
    return mapping


def nearby_candidates(
    cluster: PhotoCluster,
    markers: Iterable[dict[str, Any]],
    *,
    radius_m: float,
    artist_slug: str = "",
) -> list[dict[str, Any]]:
    """Return nearby marker evidence without downloading images."""

    if cluster.latitude is None or cluster.longitude is None:
        return []
    candidates = []
    for marker in markers:
        latitude = marker.get("latitude")
        longitude = marker.get("longitude")
        if latitude is None or longitude is None:
            continue
        distance = haversine_m(
            cluster.latitude,
            cluster.longitude,
            float(latitude),
            float(longitude),
        )
        if distance <= radius_m:
            candidates.append({
                **marker,
                "distance_m": round(distance, 1),
                "tag_match": bool(
                    artist_slug
                    and marker.get("artist_slug") == artist_slug
                ),
            })
    return sorted(
        candidates,
        key=lambda marker: (
            not marker["tag_match"],
            marker["distance_m"],
            marker["marker_id"],
        ),
    )


def _reference_path(cache_directory: Path, marker_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", marker_id).strip("-")
    if not safe_id:
        raise ValueError("Marker has no cache-safe identifier")
    return cache_directory / f"{safe_id}.jpg"


def cache_reference_image(
    marker: dict[str, Any],
    cache_directory: Path,
    *,
    timeout_seconds: int = 30,
    maximum_bytes: int = 20_000_000,
    session: requests.Session | None = None,
) -> Path | None:
    """Cache one public marker image with scheme, type, and size limits."""

    image_url = str(marker.get("image_url") or "")
    parsed = urlparse(image_url)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    path = _reference_path(cache_directory, str(marker["marker_id"]))
    if path.is_file() and path.stat().st_size:
        return path
    client = session or requests.Session()
    response = client.get(
        image_url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout_seconds,
        stream=True,
    )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").casefold()
    if not content_type.startswith("image/"):
        raise ValueError("Street Art Cities reference response is not an image")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    size = 0
    try:
        with temporary.open("wb") as stream:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > maximum_bytes:
                    raise ValueError("Street Art Cities reference image is too large")
                stream.write(chunk)
        with Image.open(temporary) as image:
            image.verify()
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def compare_clusters(
    clusters: Iterable[PhotoCluster],
    city_payload: dict[str, Any],
    *,
    artist_mapping_path: Path,
    reference_cache: Path,
    candidate_radius_m: float,
    visual_enabled: bool,
    profile: str,
    session: requests.Session | None = None,
) -> dict[str, dict[str, Any]]:
    """Produce bounded nearby SAC evidence for each local cluster."""

    if profile not in PROFILE_LIMITS:
        raise ValueError("Unknown visual matching profile")
    mapping = load_artist_mapping(artist_mapping_path)
    markers = city_payload["markers"]
    results = {}
    for cluster in clusters:
        slug = mapping.get(cluster.tag.casefold(), "")
        candidates = nearby_candidates(
            cluster,
            markers,
            radius_m=candidate_radius_m,
            artist_slug=slug,
        )[:PROFILE_LIMITS[profile]]
        if visual_enabled and cluster.photos:
            for candidate in candidates:
                try:
                    reference = cache_reference_image(
                        candidate, reference_cache, session=session
                    )
                    similarity = (
                        image_similarity(cluster.photos[0].path, reference)
                        if reference else None
                    )
                except (requests.RequestException, OSError, ValueError) as exc:
                    reference = None
                    similarity = None
                    candidate["visual_error"] = str(exc)
                candidate["cached_image"] = str(reference) if reference else None
                candidate["visual_similarity"] = similarity
        best = candidates[0] if candidates else None
        verified = [
            candidate
            for candidate in candidates
            if candidate.get("visual_similarity") is not None
            and candidate["visual_similarity"] >= 0.08
        ]
        if verified:
            status = "likely-present"
            recommendation = "Review the matching Street Art Cities marker"
        elif best and best["tag_match"]:
            status = "review"
            recommendation = "Review nearby same-artist marker"
        elif best:
            status = "review"
            recommendation = "Review nearby marker"
        else:
            status = "likely-new"
            recommendation = "No nearby Street Art Cities marker found"
        results[cluster.id] = {
            "city": city_payload["city"],
            "status": status,
            "recommendation": recommendation,
            "artist_slug": slug or None,
            "candidates": candidates,
        }
    return results
