"""Optional Street Art Cities public-data adapter."""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlencode, urljoin, urlparse

import requests
from PIL import Image

from . import __version__
from .clustering import haversine_m
from .matching import image_similarity
from .models import PhotoCluster

BASE_URL = "https://streetartcities.com"
MARKERS_URL = BASE_URL + "/data/cities/{city}/markers.json"
OAUTH_AUTHORIZE_URL = BASE_URL + "/api/oauth/authorize"
OAUTH_TOKEN_URL = BASE_URL + "/api/oauth/token"
COLLECTIONS_URL = BASE_URL + "/api/collections"
MARKERS_SEARCH_URL = BASE_URL + "/api/markers/search"
CITY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
USER_AGENT = (
    f"StreetArtPhotoAssistant/{__version__} "
    "(local desktop application; public SAC adapter)"
)
PROFILE_LIMITS = {"quick": 4, "balanced": 8, "thorough": 16}
ProgressCallback = Callable[[str, int, int, str], None]


def create_pkce_pair() -> tuple[str, str]:
    """Create one RFC 7636 verifier and S256 challenge."""

    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def oauth_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    scope: str,
    state: str,
    code_challenge: str,
) -> str:
    """Build the SAC public-client authorization URL."""

    if not all((client_id, redirect_uri, scope, state, code_challenge)):
        raise ValueError("Complete OAuth authorization parameters are required")
    return OAUTH_AUTHORIZE_URL + "?" + urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })


def exchange_pkce_code(
    *,
    client_id: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
    timeout_seconds: int = 30,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Exchange one authorization code without using a client secret."""

    client = session or requests.Session()
    try:
        response = client.post(
            OAUTH_TOKEN_URL,
            json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": code_verifier,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Street Art Cities token exchange failed: {exc}"
        ) from exc
    if not isinstance(payload, dict) or not str(payload.get("access_token") or ""):
        raise ValueError("Street Art Cities returned no access token")
    if str(payload.get("token_type") or "Bearer").casefold() != "bearer":
        raise ValueError("Street Art Cities returned an unsupported token type")
    return payload


def fetch_collections(
    access_token: str,
    *,
    timeout_seconds: int = 30,
    session: requests.Session | None = None,
) -> Any:
    """Make the documented first authenticated API request."""

    if not access_token:
        raise ValueError("A Street Art Cities access token is required")
    client = session or requests.Session()
    try:
        response = client.get(
            COLLECTIONS_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": USER_AGENT,
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Street Art Cities collections request failed: {exc}"
        ) from exc


def refresh_city_api(
    city: str,
    cache_directory: Path,
    *,
    access_token: str,
    timeout_seconds: int = 30,
    session: requests.Session | None = None,
    throttle: RequestThrottle | None = None,
) -> dict[str, Any]:
    """Refresh one city through the authenticated paginated Markers API."""

    city = city.strip().lower()
    if not CITY_RE.fullmatch(city):
        raise ValueError("City must be a lowercase slug")
    if not access_token:
        raise ValueError("A Street Art Cities access token is required")
    client = session or requests.Session()
    markers: list[dict[str, Any]] = []
    page = 1
    total: int | None = None
    while total is None or len(markers) < total:
        if page > 100:
            raise ValueError(
                "Street Art Cities marker search exceeds 10,000 results"
            )
        if throttle is not None:
            throttle.wait()
        try:
            response = client.get(
                MARKERS_SEARCH_URL,
                params={
                    "city": city,
                    "type": "artwork",
                    "status": "all",
                    "page": page,
                    "perPage": 100,
                },
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "User-Agent": USER_AGENT,
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            raw = response.json()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Street Art Cities marker search failed: {exc}"
            ) from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
            raise ValueError(
                "Street Art Cities marker search returned no items list"
            )
        try:
            response_total = int(raw["total"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "Street Art Cities marker search returned no valid total"
            ) from exc
        if total is None:
            total = response_total
        elif total != response_total:
            raise ValueError(
                "Street Art Cities marker total changed during pagination"
            )
        items = [
            _normalize_marker(item)
            for item in raw["items"]
            if isinstance(item, dict)
            and item.get("type") == "artwork"
            and item.get("id")
        ]
        markers.extend(items)
        if not raw["items"]:
            if len(markers) < total:
                raise ValueError(
                    "Street Art Cities marker pagination ended early"
                )
            break
        page += 1
    payload = {
        "version": 1,
        "city": city,
        "source": "oauth-markers-api",
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "markers": markers,
    }
    _atomic_json(cache_directory / f"{city}.json", payload)
    return payload


@dataclass
class RequestThrottle:
    """Enforce a minimum interval between provider requests."""

    interval_seconds: float
    _last_request: float | None = field(default=None, init=False)

    def wait(self) -> None:
        if self.interval_seconds < 0:
            raise ValueError("Request interval cannot be negative")
        now = time.monotonic()
        if self._last_request is not None:
            remaining = self.interval_seconds - (now - self._last_request)
            if remaining > 0:
                time.sleep(remaining)
                now = time.monotonic()
        self._last_request = now


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
    throttle: RequestThrottle | None = None,
) -> dict[str, Any]:
    """Refresh one complete city marker cache with a single bounded request."""

    city = city.strip().lower()
    if not CITY_RE.fullmatch(city):
        raise ValueError("City must be a lowercase slug")
    client = session or requests.Session()
    if throttle is not None:
        throttle.wait()
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
        "source": "public-city-endpoint",
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
    artist_tag: str = "",
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
            artist_names = {
                name.strip().casefold()
                for name in str(marker.get("artist") or "").split(",")
                if name.strip()
            }
            candidates.append({
                **marker,
                "distance_m": round(distance, 1),
                "tag_match": bool(
                    (
                        artist_slug
                        and marker.get("artist_slug") == artist_slug
                    )
                    or (
                        artist_tag
                        and artist_tag.casefold() in artist_names
                    )
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
    throttle: RequestThrottle | None = None,
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
    if throttle is not None:
        throttle.wait()
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


def cache_city_images(
    markers: Iterable[dict[str, Any]],
    cache_directory: Path,
    *,
    session: requests.Session | None = None,
    throttle: RequestThrottle | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, int]:
    """Cache every available city marker image without failing the city run."""

    downloadable = [
        marker for marker in markers if marker.get("image_url")
    ]
    cached = 0
    failed = 0
    for index, marker in enumerate(downloadable, start=1):
        if progress is not None:
            progress(
                "sac-city-images",
                index,
                len(downloadable),
                f"Caching SAC city picture {index} of {len(downloadable)}",
            )
        try:
            reference = cache_reference_image(
                marker,
                cache_directory,
                session=session,
                throttle=throttle,
            )
            marker["cached_image"] = str(reference) if reference else None
            if reference:
                cached += 1
        except (requests.RequestException, OSError, ValueError) as exc:
            marker["cached_image"] = None
            marker["visual_error"] = str(exc)
            failed += 1
    return {
        "available": len(downloadable),
        "cached": cached,
        "failed": failed,
    }


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
    throttle: RequestThrottle | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, dict[str, Any]]:
    """Produce bounded nearby SAC evidence for each local cluster."""

    if profile not in PROFILE_LIMITS:
        raise ValueError("Unknown visual matching profile")
    mapping = load_artist_mapping(artist_mapping_path)
    markers = city_payload["markers"]
    cluster_list = list(clusters)
    prepared = []
    for index, cluster in enumerate(cluster_list, start=1):
        slug = mapping.get(cluster.tag.casefold(), "")
        candidates = nearby_candidates(
            cluster,
            markers,
            radius_m=candidate_radius_m,
            artist_slug=slug,
            artist_tag=cluster.tag,
        )[:PROFILE_LIMITS[profile]]
        prepared.append((cluster, slug, candidates))
        if progress is not None:
            progress(
                "sac-matching",
                index,
                len(cluster_list),
                f"Gathered nearby SAC candidates for cluster {index}",
            )
    image_total = (
        sum(
            len(candidates)
            for cluster, _slug, candidates in prepared
            if cluster.photos
        )
        if visual_enabled else 0
    )
    image_current = 0
    results = {}
    for cluster, slug, candidates in prepared:
        if visual_enabled and cluster.photos:
            for candidate in candidates:
                image_current += 1
                if progress is not None:
                    progress(
                        "sac-images",
                        image_current,
                        image_total,
                        (
                            f"Checking SAC reference image {image_current} "
                            f"of {image_total}"
                        ),
                    )
                try:
                    cached = candidate.get("cached_image")
                    reference = (
                        Path(str(cached))
                        if cached and Path(str(cached)).is_file()
                        else cache_reference_image(
                            candidate,
                            reference_cache,
                            session=session,
                            throttle=throttle,
                        )
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
            "marker_source": city_payload.get(
                "source", "public-city-endpoint"
            ),
            "status": status,
            "recommendation": recommendation,
            "artist_slug": slug or None,
            "candidates": candidates,
        }
    return results
