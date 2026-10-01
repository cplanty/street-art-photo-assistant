"""Local Flask application for generation and cluster review."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import secrets
import subprocess
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from .config import CITY_SLUG_RE, resolve_local_path, save_config, validate_config
from .diagnostics import create_diagnostic_bundle
from .gps import (
    apply_gps_plan,
    build_individual_gps_plan,
    build_manual_gps_plan,
    build_missing_gps_plan,
)
from .metadata import apply_tag_edit_plan, build_tag_edit_plan
from .models import FileFingerprint, PhotoRecord
from .photos import read_photo
from .runs import RunManager
from .sac import (
    SACAuthorizationError,
    RequestThrottle,
    cached_cities,
    create_pkce_pair,
    exchange_pkce_code,
    fetch_collections,
    oauth_authorization_url,
    refresh_city_artists,
    request_media_upload,
    submit_marker_creation,
    upload_media_file,
)
from .workflow import scan_and_select, sources_from_config

SAC_OAUTH_REDIRECT_URI = "http://127.0.0.1:8787/login"
SAC_OAUTH_SCOPE = (
    "collections:read markers:read artists:read edits:read edits:write"
)
SAC_OAUTH_PENDING_SECONDS = 600
SAC_PROPOSAL_PENDING_SECONDS = 3600
SAC_REQUIRED_PROPOSAL_SCOPES = {"edits:read", "edits:write"}


def _signature(config: dict[str, Any]) -> str:
    signed = deepcopy(config)
    signed.pop("run_label", None)
    encoded = json.dumps(
        signed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    os.replace(temporary, path)


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _is_local_request() -> bool:
    return request.remote_addr in {"127.0.0.1", "::1"}


def _inside(path: Path, roots: list[Path]) -> bool:
    resolved = path.resolve()
    return any(
        resolved == root or resolved.is_relative_to(root)
        for root in roots
    )


ARTIST_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
INSTAGRAM_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]+$")


def _instagram_handle(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if "://" in value:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Instagram URL must use HTTP or HTTPS")
        if parsed.netloc.casefold() not in {
            "instagram.com", "www.instagram.com"
        }:
            raise ValueError("Instagram URL must use instagram.com")
        value = parsed.path.strip("/").split("/", 1)[0]
    value = value.lstrip("@")
    if value and not INSTAGRAM_HANDLE_RE.fullmatch(value):
        raise ValueError("Instagram must be a handle or profile URL")
    return value


ARTIST_FIELDS = [
    "tag",
    "streetartcities_slug",
    "streetartcities_name",
    "instagram",
    "status",
]


def _artist_tags(
    paths: Path | list[Path] | tuple[Path, ...],
) -> tuple[list[str], dict[str, list[str]], dict[str, dict[str, str]]]:
    tags: list[str] = []
    by_slug: dict[str, list[str]] = {}
    details_by_slug: dict[str, dict[str, str]] = {}
    sources = [paths] if isinstance(paths, Path) else list(paths)
    seen_tags: set[str] = set()
    for path in sources:
        if not path.is_file():
            continue
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream, delimiter=";"):
                tag = str(row.get("tag") or "").strip()
                slug = str(row.get("streetartcities_slug") or "").strip()
                name = str(row.get("streetartcities_name") or "").strip()
                instagram = str(row.get("instagram") or "").strip()
                folded = tag.casefold()
                if not tag or folded in seen_tags:
                    continue
                seen_tags.add(folded)
                tags.append(tag)
                if slug:
                    by_slug.setdefault(slug, []).append(tag)
                    details = details_by_slug.setdefault(
                        slug, {"tag": tag, "name": "", "instagram_url": ""}
                    )
                    if name and not details["name"]:
                        details["name"] = name
                    if instagram and not details["instagram_url"]:
                        try:
                            handle = _instagram_handle(instagram)
                        except ValueError:
                            handle = ""
                        if handle:
                            details["instagram_url"] = (
                                "https://www.instagram.com/"
                                f"{quote(handle, safe='')}/"
                            )
    return sorted(set(tags), key=str.casefold), by_slug, details_by_slug


def _artist_defaults(path: Path, tag: str) -> dict[str, Any]:
    if not path.is_file() or not tag:
        return {}
    try:
        payload = _load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Could not read artist descriptions: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("Artist descriptions must be a JSON object")
    folded = tag.casefold()
    for name, value in payload.items():
        if str(name).casefold() != folded:
            continue
        if isinstance(value, str):
            return {"description": value}
        if isinstance(value, dict):
            return value
        raise ValueError(f"Artist description for {tag} is invalid")
    return {}


def _photo_content_type(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    raise ValueError("Street Art Cities accepts JPEG or PNG images")


def _uploaded_image(
    public_url: str,
    *,
    attribution: str,
) -> dict[str, Any]:
    if public_url.endswith("/orig.jpg"):
        stem = public_url[:-len("orig.jpg")]
        extension = "jpg"
    elif public_url.endswith("/orig.png"):
        stem = public_url[:-len("orig.png")]
        extension = "png"
    else:
        raise ValueError("Street Art Cities returned an unknown image URL")
    return {
        "id": str(uuid.uuid4()),
        "url": public_url,
        "sizes": {
            "small": f"{stem}512.{extension}",
            "medium": f"{stem}1024.{extension}",
            "large": f"{stem}2048.{extension}",
        },
        "attribution": attribution.strip(),
    }


def _append_artist(
    path: Path,
    *,
    tag: str,
    slug: str,
    name: str = "",
    instagram: str,
) -> bool:
    tag = tag.strip()
    slug = slug.strip().lower()
    name = name.strip()
    if not tag or len(tag) > 200 or "\n" in tag or "\r" in tag:
        raise ValueError("Artist tag is required and must fit on one line")
    if tag.startswith("_"):
        raise ValueError("Internal tags are not added to artists.csv")
    if slug and not ARTIST_SLUG_RE.fullmatch(slug):
        raise ValueError("Street Art Cities slug is invalid")
    if len(name) > 200 or "\n" in name or "\r" in name:
        raise ValueError(
            "Street Art Cities name must fit on one line"
        )
    if name and not slug:
        raise ValueError(
            "Street Art Cities name requires a slug"
        )
    handle = _instagram_handle(instagram)
    fields = list(ARTIST_FIELDS)
    rows: list[dict[str, str]] = []
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = [
                {field: str(row.get(field) or "") for field in fields}
                for row in csv.DictReader(stream, delimiter=";")
            ]
    if any(row["tag"].casefold() == tag.casefold() for row in rows):
        return False
    rows.append({
        "tag": tag,
        "streetartcities_slug": slug,
        "streetartcities_name": name,
        "instagram": handle,
        "status": "confirmed" if slug else "",
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=fields, delimiter=";", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _fill_artist_names(
    path: Path, names_by_slug: dict[str, str]
) -> dict[str, Any]:
    """Fill only blank display names, never overwriting a curated value."""

    if not path.is_file():
        raise ValueError("The artist mapping file does not exist")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        fields = list(reader.fieldnames or ARTIST_FIELDS)
        rows = [dict(row) for row in reader]
    if "streetartcities_name" not in fields:
        fields.insert(
            fields.index("streetartcities_slug") + 1, "streetartcities_name"
        )
    filled: list[dict[str, str]] = []
    unresolved: list[str] = []
    for row in rows:
        row.pop(None, None)
        slug = str(row.get("streetartcities_slug") or "").strip()
        if not slug:
            continue
        current = str(row.get("streetartcities_name") or "").strip()
        if current:
            continue
        name = names_by_slug.get(slug.casefold(), "")
        if name:
            row["streetartcities_name"] = name
            filled.append({"tag": str(row.get("tag") or ""), "slug": slug,
                           "name": name})
        else:
            unresolved.append(slug)
    if filled:
        temporary = path.with_name(path.name + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=fields,
                    delimiter=";",
                    lineterminator="\n",
                )
                writer.writeheader()
                writer.writerows(
                    {field: (row.get(field) or "") for field in fields}
                    for row in rows
                )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return {
        "filled": filled,
        "unresolved_slugs": sorted(set(unresolved)),
        "rows": len(rows),
    }


def _suggest_artist_slugs(
    paths: Path | list[Path] | tuple[Path, ...],
    artists: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Propose provider identities for unmapped tags without writing them."""

    by_name: dict[str, dict[str, Any]] = {}
    for artist in artists:
        slug = str(artist.get("slug") or "")
        if not slug:
            continue
        titles = [str(artist.get("name") or "")]
        titles.extend(str(title) for title in artist.get("alternative_names") or [])
        for title in titles:
            key = title.strip().casefold()
            if key and key not in by_name:
                by_name[key] = artist
    suggestions = []
    sources = [paths] if isinstance(paths, Path) else list(paths)
    seen_tags: set[str] = set()
    for path in sources:
        if not path.is_file():
            continue
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream, delimiter=";"):
                tag = str(row.get("tag") or "").strip()
                slug = str(row.get("streetartcities_slug") or "").strip()
                folded = tag.casefold()
                if not tag or folded in seen_tags:
                    continue
                seen_tags.add(folded)
                if slug or tag.startswith("_"):
                    continue
                match = by_name.get(folded)
                if match:
                    suggestions.append({
                        "tag": tag,
                        "slug": str(match.get("slug") or ""),
                        "name": str(match.get("name") or ""),
                    })
    return suggestions


def _choose_folder(initial: str) -> str:
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as exc:
        raise RuntimeError("The native folder requester is unavailable") from exc
    try:
        root = tkinter.Tk()
    except tkinter.TclError as exc:
        raise RuntimeError(
            f"Could not open the native folder requester: {exc}"
        ) from exc
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        try:
            return filedialog.askdirectory(
                parent=root,
                title="Select a photo folder",
                initialdir=initial if Path(initial).is_dir() else None,
                mustexist=True,
            ) or ""
        except tkinter.TclError as exc:
            raise RuntimeError(f"Folder requester failed: {exc}") from exc
    finally:
        root.destroy()


def create_app(
    config: dict[str, Any],
    config_path: Path,
    *,
    run_manager: RunManager | None = None,
) -> Flask:
    """Create the local application without starting a server."""

    config_path = config_path.resolve()
    config_root = config_path.parent
    state: dict[str, Any] = {
        "config": deepcopy(config),
        "previews": {},
        "sac_oauth_pending": {},
        "sac_oauth_token": None,
        "sac_proposals": {},
    }
    runs_path = resolve_local_path(
        config_root, str(config["paths"]["runs"])
    )
    manager = run_manager or RunManager(runs_path)
    plan_root = manager.run_root / "_plans"
    plan_root.mkdir(parents=True, exist_ok=True)
    app_log_path = manager.run_root / "_logs" / "app.jsonl"
    app_log_lock = threading.Lock()

    app = Flask(__name__)
    app.config["ASSISTANT_STATE"] = state
    app.config["ASSISTANT_CONFIG_PATH"] = config_path
    app.config["RUN_MANAGER"] = manager

    def current_config() -> dict[str, Any]:
        return state["config"]

    def append_app_event(payload: dict[str, Any]) -> None:
        event = {
            "timestamp": datetime.now().astimezone().isoformat(),
            **payload,
        }
        app_log_path.parent.mkdir(parents=True, exist_ok=True)
        with app_log_lock:
            if app_log_path.is_file() and app_log_path.stat().st_size >= 2_000_000:
                oldest = app_log_path.with_suffix(".jsonl.3")
                oldest.unlink(missing_ok=True)
                for index in (2, 1):
                    source = app_log_path.with_suffix(f".jsonl.{index}")
                    if source.is_file():
                        os.replace(
                            source,
                            app_log_path.with_suffix(f".jsonl.{index + 1}"),
                        )
                os.replace(
                    app_log_path,
                    app_log_path.with_suffix(".jsonl.1"),
                )
            with app_log_path.open(
                "a", encoding="utf-8", newline="\n"
            ) as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def source_roots() -> list[Path]:
        return [
            source.path.resolve()
            for source in sources_from_config(current_config(), config_root)
            if source.enabled
        ]

    def artist_paths() -> tuple[Path, Path]:
        paths = current_config()["paths"]
        return (
            resolve_local_path(config_root, str(paths["artists"])),
            resolve_local_path(config_root, str(paths["local_artists"])),
        )

    def require_preview(token: str, submitted: dict[str, Any]) -> None:
        preview = state["previews"].get(token)
        if preview is None or preview["signature"] != _signature(submitted):
            raise ValueError("Preview the unchanged selection first")

    def plan_path(identifier: str) -> Path:
        if not identifier or Path(identifier).name != identifier:
            raise ValueError("Invalid plan id")
        path = (plan_root / f"{identifier}.json").resolve()
        if not path.is_relative_to(plan_root.resolve()):
            raise ValueError("Plan path escapes the run root")
        return path

    def save_plan(plan: dict[str, Any]) -> None:
        _atomic_json(plan_path(str(plan["id"])), plan)

    def load_plan(identifier: str) -> dict[str, Any]:
        path = plan_path(identifier)
        if not path.is_file():
            raise ValueError("Unknown or expired plan")
        return _load_json(path)

    def report_cluster(run_id: str, cluster_id: str) -> dict[str, Any]:
        report = manager.report(run_id)
        for cluster in report["clusters"]:
            if cluster["id"] == cluster_id:
                return cluster
        raise ValueError("Unknown cluster")

    def ordered_clusters(
        run_id: str,
        sort: str,
        direction: str,
    ) -> list[dict[str, Any]]:
        clusters = manager.report(run_id)["clusters"]
        indexed = [(index + 1, cluster) for index, cluster in enumerate(clusters)]
        keys = {
            "index": lambda item: item[0],
            "tag": lambda item: str(item[1].get("tag") or "").casefold(),
            "time": lambda item: str(
                item[1].get("first_capture") or "9999"
            ),
            "photos": lambda item: (
                len(item[1].get("photos") or [])
                + len(item[1].get("context_photos") or [])
            ),
            "status": lambda item: str(
                (item[1].get("street_art_cities") or {}).get("status") or ""
            ),
        }
        key = keys.get(sort, keys["index"])
        indexed.sort(key=key, reverse=direction == "desc")
        ordered = []
        for index, cluster in indexed:
            payload = deepcopy(cluster)
            payload["_index"] = index
            ordered.append(payload)
        return ordered

    def cluster_paths(cluster: dict[str, Any]) -> list[Path]:
        return [
            Path(photo["path"]).resolve()
            for photo in [*cluster["photos"], *cluster["context_photos"]]
        ]

    def refreshed_cluster(run_id: str, cluster_id: str) -> dict[str, Any]:
        cluster = deepcopy(report_cluster(run_id, cluster_id))
        located = []
        for group in ("photos", "context_photos"):
            refreshed = []
            for stored in cluster[group]:
                photo = read_photo(
                    Path(stored["path"]), str(stored.get("source") or "")
                )
                payload = photo.to_dict()
                payload["filename"] = photo.path.name
                refreshed.append(payload)
                if photo.has_gps:
                    located.append(photo)
            cluster[group] = refreshed
        if located:
            cluster["latitude"] = sum(
                photo.latitude for photo in located
                if photo.latitude is not None
            ) / len(located)
            cluster["longitude"] = sum(
                photo.longitude for photo in located
                if photo.longitude is not None
            ) / len(located)
        return cluster

    @app.errorhandler(ValueError)
    def value_error(exc: ValueError):
        append_app_event({
            "kind": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
        })
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": str(exc)}), 400
        return str(exc), 400

    @app.errorhandler(OSError)
    def os_error(exc: OSError):
        append_app_event({
            "kind": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
        })
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": str(exc)}), 500
        return str(exc), 500

    @app.errorhandler(RuntimeError)
    def runtime_error(exc: RuntimeError):
        append_app_event({
            "kind": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
        })
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": str(exc)}), 500
        return str(exc), 500

    @app.before_request
    def start_request_timer() -> None:
        g.request_started = time.monotonic()

    @app.after_request
    def log_request(response):
        started = getattr(g, "request_started", None)
        duration_ms = (
            round((time.monotonic() - started) * 1000, 1)
            if started is not None else None
        )
        append_app_event({
            "kind": "request",
            "method": request.method,
            "route": (
                request.url_rule.rule
                if request.url_rule is not None else "<unmatched>"
            ),
            "status": response.status_code,
            "duration_ms": duration_ms,
        })
        return response

    @app.get("/")
    def index() -> str:
        token = state["sac_oauth_token"]
        connected = bool(
            token and float(token["expires_at"]) > time.time()
        )
        runs = manager.list_runs()
        active_run = next(
            (
                run for run in runs
                if run.get("status") in {"queued", "running"}
            ),
            None,
        )
        return render_template(
            "index.html",
            config=current_config(),
            config_path=config_path,
            artists_path=artist_paths()[0],
            local_artists_path=artist_paths()[1],
            cached_cities=cached_cities(resolve_local_path(
                config_root, str(current_config()["paths"]["city_cache"])
            )),
            sac_api_connected=connected,
            sac_api_scopes=(
                sorted(set(str(token.get("scope") or "").split()))
                if connected else []
            ),
            active_run_id=(
                str(active_run["id"]) if active_run is not None else None
            ),
            runs=runs,
        )

    @app.get("/login")
    def sac_login():
        if not _is_local_request():
            abort(403)
        pending: dict[str, dict[str, Any]] = state["sac_oauth_pending"]
        now = time.time()
        for identifier, item in list(pending.items()):
            if now - float(item["created_at"]) > SAC_OAUTH_PENDING_SECONDS:
                pending.pop(identifier, None)

        returned_state = str(request.args.get("state") or "")
        code = str(request.args.get("code") or "")
        oauth_error = str(request.args.get("error") or "")
        if code or oauth_error or returned_state:
            attempt = pending.pop(returned_state, None)
            if attempt is None:
                raise ValueError("OAuth state is missing, expired, or invalid")
            if oauth_error:
                return render_template(
                    "login.html",
                    connected=False,
                    error=f"Street Art Cities authorization failed: {oauth_error}",
                ), 400
            if not code:
                raise ValueError("Street Art Cities returned no authorization code")
            token_payload = exchange_pkce_code(
                client_id=str(attempt["client_id"]),
                redirect_uri=SAC_OAUTH_REDIRECT_URI,
                code=code,
                code_verifier=str(attempt["code_verifier"]),
            )
            expires_in = max(0, int(token_payload.get("expires_in") or 0))
            state["sac_oauth_token"] = {
                "access_token": str(token_payload["access_token"]),
                "scope": str(token_payload.get("scope") or ""),
                "expires_at": now + expires_in,
            }
            return render_template(
                "login.html",
                connected=True,
                error=None,
            )

        client_id = str(
            current_config()["matching"].get("api_client_id") or ""
        ).strip()
        if not client_id:
            raise ValueError(
                "Configure matching.api_client_id before connecting "
                "Street Art Cities"
            )
        verifier, challenge = create_pkce_pair()
        identifier = secrets.token_urlsafe(32)
        pending[identifier] = {
            "client_id": client_id,
            "code_verifier": verifier,
            "created_at": now,
        }
        while len(pending) > 10:
            pending.pop(next(iter(pending)))
        return redirect(oauth_authorization_url(
            client_id=client_id,
            redirect_uri=SAC_OAUTH_REDIRECT_URI,
            scope=SAC_OAUTH_SCOPE,
            state=identifier,
            code_challenge=challenge,
        ))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/sac/collections")
    def sac_collections():
        if not _is_local_request():
            abort(403)
        token = state["sac_oauth_token"]
        if token is None or float(token["expires_at"]) <= time.time():
            state["sac_oauth_token"] = None
            return jsonify({
                "ok": False,
                "error": "Connect Street Art Cities before testing the API",
            }), 401
        return jsonify({
            "ok": True,
            "collections": fetch_collections(str(token["access_token"])),
        })

    @app.post("/api/sac/disconnect")
    def sac_disconnect():
        if not _is_local_request():
            abort(403)
        state["sac_oauth_token"] = None
        state["sac_oauth_pending"].clear()
        return jsonify({"ok": True})

    @app.post("/api/config")
    def update_config():
        payload = request.get_json(force=True)
        if not isinstance(payload, dict):
            raise ValueError("Configuration must be an object")
        validate_config(payload)
        save_config(config_path, payload)
        state["config"] = deepcopy(payload)
        return jsonify({"ok": True})

    @app.post("/api/artists")
    def add_artist():
        if not _is_local_request():
            return jsonify({"ok": False, "error": "Local access only"}), 403
        if current_config().get("read_only"):
            return jsonify({"ok": False, "error": "Read-only mode"}), 403
        payload = request.get_json(force=True)
        main_artists_path, local_artists_path = artist_paths()
        destination = str(payload.get("destination") or "main")
        if destination not in {"main", "local"}:
            raise ValueError("Artist mapping destination must be main or local")
        destination_path = (
            main_artists_path if destination == "main" else local_artists_path
        )
        tag = str(payload.get("tag") or "").strip()
        known_tags, _by_slug, _details = _artist_tags(
            (main_artists_path, local_artists_path)
        )
        if any(known.casefold() == tag.casefold() for known in known_tags):
            return jsonify({
                "ok": True,
                "added": False,
                "path": str(destination_path),
            })
        added = _append_artist(
            destination_path,
            tag=tag,
            slug=str(payload.get("slug") or ""),
            name=str(payload.get("name") or ""),
            instagram=str(payload.get("instagram") or ""),
        )
        return jsonify({
            "ok": True,
            "added": added,
            "path": str(destination_path),
        })

    @app.post("/api/artists/catalog")
    def refresh_artist_catalog():
        if not _is_local_request():
            return jsonify({"ok": False, "error": "Local access only"}), 403
        if current_config().get("read_only"):
            return jsonify({"ok": False, "error": "Read-only mode"}), 403
        payload = request.get_json(silent=True) or {}
        config = current_config()
        city = str(
            payload.get("city") or config["matching"].get("city") or ""
        ).strip().lower()
        if not city:
            raise ValueError("A Street Art Cities city slug is required")
        token = state["sac_oauth_token"]
        if token is None or float(token["expires_at"]) <= time.time():
            raise ValueError(
                "Connect the Street Art Cities API before refreshing "
                "the artist catalogue"
            )
        scopes = set(str(token.get("scope") or "").split())
        if "artists:read" not in scopes:
            raise ValueError(
                "Reconnect Street Art Cities to grant artists:read"
            )
        cache_directory = resolve_local_path(
            config_root, str(config["paths"]["city_cache"])
        )
        artists_paths = artist_paths()
        catalog = refresh_city_artists(
            city,
            cache_directory,
            access_token=str(token["access_token"]),
            throttle=RequestThrottle(
                float(config["matching"].get("request_interval_seconds", 0.5))
            ),
        )
        names_by_slug = {
            str(artist["slug"]).casefold(): str(artist["name"])
            for artist in catalog["artists"]
            if artist.get("slug") and artist.get("name")
        }
        results = [
            _fill_artist_names(path, names_by_slug)
            for path in artists_paths
            if path.is_file()
        ]
        return jsonify({
            "ok": True,
            "city": city,
            "artists": len(catalog["artists"]),
            "filled": [
                item for result in results for item in result["filled"]
            ],
            "unresolved_slugs": sorted({
                slug
                for result in results
                for slug in result["unresolved_slugs"]
            }),
            "suggestions": _suggest_artist_slugs(
                artists_paths, catalog["artists"]
            ),
            "path": str(artists_paths[0]),
            "local_path": str(artists_paths[1]),
        })

    @app.post("/api/browse-folder")
    def browse_folder():
        if not _is_local_request():
            abort(403)
        payload = request.get_json(silent=True) or {}
        path = _choose_folder(str(payload.get("initial") or ""))
        return jsonify({
            "ok": True,
            "path": path,
            "name": Path(path).name if path else "",
        })

    @app.post("/api/open-local")
    def open_local():
        if not _is_local_request():
            abort(403)
        payload = request.get_json(force=True)
        target = str(payload.get("target") or "")
        if target == "config":
            path = config_path
            if not path.exists():
                save_config(path, current_config())
        elif target == "artists":
            path = artist_paths()[0]
        elif target == "local-artists":
            path = artist_paths()[1]
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(path.name + ".tmp")
                temporary.write_text(
                    ";".join(ARTIST_FIELDS) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                os.replace(temporary, path)
        elif target == "diagnostics":
            path = manager.run_root / "_diagnostics"
            path.mkdir(parents=True, exist_ok=True)
        else:
            candidate = Path(target).resolve()
            if not _inside(candidate, source_roots()):
                raise ValueError("Local path is outside configured sources")
            path = candidate
        if not path.exists():
            raise ValueError(f"Local path does not exist: {path}")
        if not hasattr(os, "startfile"):
            raise RuntimeError("Opening local files is supported on Windows")
        action = str(payload.get("action") or "open")
        if action == "explorer":
            subprocess.Popen([
                "explorer.exe",
                "/select,",
                os.path.normpath(path),
            ])
        elif action == "open":
            os.startfile(os.path.normpath(path))  # type: ignore[attr-defined]
        else:
            raise ValueError("Unknown local open action")
        return jsonify({"ok": True})

    @app.post("/api/diagnostics")
    def diagnostics():
        payload = request.get_json(silent=True) or {}
        detailed = bool(payload.get("detailed"))
        bundle = create_diagnostic_bundle(
            config=current_config(),
            run_root=manager.run_root,
            runs=manager.list_runs(),
            detailed=detailed,
        )
        return jsonify({
            "ok": True,
            "path": str(bundle),
            "level": "detailed" if detailed else "safe",
        })

    @app.post("/api/preview")
    def preview():
        submitted = request.get_json(force=True)
        validate_config(submitted)
        scanned, selected, summary = scan_and_select(submitted, config_root)
        token = uuid.uuid4().hex
        state["previews"][token] = {
            "signature": _signature(submitted),
            "selected": [str(photo.path) for photo in selected],
            "created_at": datetime.now().isoformat(),
        }
        while len(state["previews"]) > 20:
            state["previews"].pop(next(iter(state["previews"])))
        return jsonify({
            "ok": True,
            "token": token,
            "preview": asdict(summary),
            "scanned_sources": sorted({photo.source for photo in scanned}),
        })

    @app.post("/api/gps/preview")
    def gps_preview():
        payload = request.get_json(force=True)
        submitted = payload.get("config")
        if not isinstance(submitted, dict):
            raise ValueError("Configuration is required")
        require_preview(str(payload.get("preview_token") or ""), submitted)
        scanned, selected, _summary = scan_and_select(submitted, config_root)
        gps_config = submitted["gps_repair"]
        plan = build_missing_gps_plan(
            selected,
            scanned,
            maximum_time_difference_seconds=int(
                gps_config["maximum_time_difference_seconds"]
            ),
            target_sources=payload.get("target_sources") or [],
            reference_sources=payload.get("reference_sources") or [],
        )
        save_plan(plan)
        return jsonify({"ok": True, "plan": plan})

    @app.post("/api/plans/<identifier>/apply")
    def apply_plan(identifier: str):
        if current_config().get("read_only"):
            return jsonify({"ok": False, "error": "Read-only mode"}), 403
        plan = load_plan(identifier)
        change_log = plan_root / f"{identifier}.changes.json"
        if plan.get("kind") == "tag-edit":
            changed = apply_tag_edit_plan(
                plan,
                allowed_roots=source_roots(),
                change_log_path=change_log,
            )
        else:
            changed = apply_gps_plan(
                plan,
                allowed_roots=source_roots(),
                change_log_path=change_log,
            )
        return jsonify({
            "ok": True,
            "changed": changed,
            "change_log": str(change_log),
        })

    @app.post("/api/runs")
    def start_run():
        payload = request.get_json(force=True)
        submitted = payload.get("config")
        if not isinstance(submitted, dict):
            raise ValueError("Configuration is required")
        validate_config(submitted)
        require_preview(str(payload.get("preview_token") or ""), submitted)
        run_config = deepcopy(submitted)
        for source in run_config["sources"]:
            source["path"] = str(resolve_local_path(
                config_root, str(source["path"])
            ))
        for key in ("artists", "city_cache", "reference_images", "runs"):
            run_config["paths"][key] = str(resolve_local_path(
                config_root, str(run_config["paths"][key])
            ))
        visual = bool(run_config["matching"].get("visual_enabled", False))
        environment = {}
        if (
            run_config["matching"].get("marker_source")
            == "oauth-markers-api"
        ):
            token = state["sac_oauth_token"]
            if token is None or float(token["expires_at"]) <= time.time():
                raise ValueError(
                    "Connect the Street Art Cities API before starting "
                    "an authenticated marker run"
                )
            scopes = set(str(token.get("scope") or "").split())
            if "markers:read" not in scopes:
                raise ValueError(
                    "Reconnect Street Art Cities to grant markers:read"
                )
            environment["SAC_API_ACCESS_TOKEN"] = str(token["access_token"])
        return jsonify({"ok": True, "run": manager.start(
            run_config,
            visual=visual,
            environment=environment,
        )})

    @app.get("/api/runs")
    def list_runs():
        return jsonify({"ok": True, "runs": manager.list_runs()})

    @app.get("/api/runs/<run_id>")
    def run_status(run_id: str):
        return jsonify({
            "ok": True,
            "run": manager.status(run_id, include_log=True),
        })

    @app.post("/api/runs/<run_id>/cancel")
    def cancel_run(run_id: str):
        return jsonify({"ok": True, "run": manager.cancel(run_id)})

    @app.delete("/api/runs/<run_id>")
    def delete_run(run_id: str):
        manager.delete(run_id)
        return jsonify({"ok": True})

    @app.get("/runs/<run_id>")
    def run_review(run_id: str):
        manifest = manager.status(run_id)
        sort = str(request.args.get("sort") or "index")
        if sort not in {"index", "tag", "time", "photos", "status"}:
            sort = "index"
        direction = str(request.args.get("dir") or "asc")
        if direction not in {"asc", "desc"}:
            direction = "asc"
        return render_template(
            "run.html",
            manifest=manifest,
            clusters=ordered_clusters(run_id, sort, direction),
            sort=sort,
            direction=direction,
        )

    @app.get("/runs/<run_id>/clusters/<cluster_id>")
    def cluster_review(run_id: str, cluster_id: str):
        cluster = refreshed_cluster(run_id, cluster_id)
        sort = str(request.args.get("sort") or "index")
        if sort not in {"index", "tag", "time", "photos", "status"}:
            sort = "index"
        direction = str(request.args.get("dir") or "asc")
        if direction not in {"asc", "desc"}:
            direction = "asc"
        artist_tags, tags_by_slug, artist_details = _artist_tags(artist_paths())
        clustering = current_config()["clustering"]
        proposals = [
            str(clustering["unknown_tag"]),
            str(clustering["wall_tag"]),
        ]
        if cluster["tag"] not in proposals:
            proposals.insert(0, str(cluster["tag"]))
        evidence = cluster.get("street_art_cities") or {}
        for candidate in evidence.get("candidates") or []:
            slug = str(candidate.get("artist_slug") or "")
            details = artist_details.get(slug) or {}
            candidate["artist_page_url"] = (
                f"https://streetartcities.com/artists/{quote(slug, safe='')}"
                if slug else None
            )
            candidate["artist_display_name"] = (
                details.get("name")
                or str(candidate.get("artist_name") or "")
                or str(candidate.get("artist") or "")
                or None
            )
            candidate["instagram_url"] = details.get("instagram_url") or None
            for tag in tags_by_slug.get(
                slug, []
            ):
                if tag not in proposals:
                    proposals.append(tag)
        autocomplete_tags = []
        for tag in [*proposals, *artist_tags]:
            if tag not in autocomplete_tags:
                autocomplete_tags.append(tag)
        photo_groups = [*cluster["photos"], *cluster["context_photos"]]
        links_by_folded_tag = {
            tag.casefold(): {
                "sac": (
                    "https://streetartcities.com/artists/"
                    f"{quote(slug, safe='')}"
                ),
                "instagram": (
                    artist_details.get(slug, {}).get("instagram_url") or None
                ),
            }
            for slug, mapped_tags in tags_by_slug.items()
            for tag in mapped_tags
        }
        common_tags = []
        if photo_groups:
            common = set(photo_groups[0]["tags"])
            for photo in photo_groups[1:]:
                common.intersection_update(photo["tags"])
            common_tags = [
                tag for tag in photo_groups[0]["tags"] if tag in common
            ]
        for photo in photo_groups:
            present = {str(tag).casefold() for tag in photo["tags"]}
            photo["tag_links"] = {
                tag: links_by_folded_tag[str(tag).casefold()]
                for tag in photo["tags"]
                if str(tag).casefold() in links_by_folded_tag
            }
            photo["proposals"] = [
                tag for tag in proposals if tag.casefold() not in present
            ]
        everywhere = set.intersection(*[
            {str(tag).casefold() for tag in photo["tags"]}
            for photo in photo_groups
        ]) if photo_groups else set()
        cluster_proposals = [
            tag for tag in proposals if tag.casefold() not in everywhere
        ]
        ids = [
            item["id"] for item in ordered_clusters(run_id, sort, direction)
        ]
        position = ids.index(cluster_id)
        return render_template(
            "cluster.html",
            run_id=run_id,
            cluster=cluster,
            known_tags=autocomplete_tags,
            artist_tags=artist_tags,
            common_tags=common_tags,
            common_tag_links={
                tag: links_by_folded_tag[str(tag).casefold()]
                for tag in common_tags
                if str(tag).casefold() in links_by_folded_tag
            },
            tag_proposals=cluster_proposals,
            previous_id=ids[(position - 1) % len(ids)],
            next_id=ids[(position + 1) % len(ids)],
            sort=sort,
            direction=direction,
            read_only=bool(current_config().get("read_only")),
        )

    @app.get("/runs/<run_id>/clusters/<cluster_id>/sac-proposal")
    def sac_proposal_review(run_id: str, cluster_id: str):
        if not _is_local_request():
            abort(403)
        now = time.time()
        pending = state["sac_proposals"]
        for identifier, item in list(pending.items()):
            if now - float(item["created_at"]) > SAC_PROPOSAL_PENDING_SECONDS:
                pending.pop(identifier, None)
        cluster = refreshed_cluster(run_id, cluster_id)
        photos = [*cluster["photos"], *cluster["context_photos"]]
        if not photos:
            raise ValueError("This cluster has no photos")
        allowed = {str(Path(photo["path"]).resolve()): photo for photo in photos}
        requested = str(request.args.get("photo") or "")
        selected_path = str(Path(requested).resolve()) if requested else str(
            Path((cluster["photos"] or photos)[0]["path"]).resolve()
        )
        if selected_path not in allowed:
            raise ValueError("Selected photo is outside this cluster")
        selected = allowed[selected_path]

        _tags, tags_by_slug, artist_details = _artist_tags(artist_paths())
        cluster_tag = str(cluster.get("tag") or "").strip()
        generic_tags = {
            str(tag).casefold()
            for tag in current_config()["clustering"]["generic_tags"]
        }
        live_tags = [
            str(tag).strip()
            for tag in selected.get("tags") or []
            if str(tag).strip()
            and not str(tag).startswith("_")
            and str(tag).casefold() not in generic_tags
        ]
        candidate_tags = [
            tag for tag in [cluster_tag, *live_tags]
            if tag and not tag.startswith("_")
        ]
        mapped_candidates = [
            (tag, slug)
            for tag in candidate_tags
            for slug, mapped_tags in tags_by_slug.items()
            if any(
                mapped.casefold() == tag.casefold()
                for mapped in mapped_tags
            )
        ]
        cluster_mapping = next(
            (
                item for item in mapped_candidates
                if item[0].casefold() == cluster_tag.casefold()
            ),
            None,
        )
        unique_mappings = list(dict.fromkeys(mapped_candidates))
        artist_tag, artist_slug = (
            cluster_mapping
            or (unique_mappings[0] if len(unique_mappings) == 1 else ("", ""))
        )
        if not artist_tag and len(live_tags) == 1:
            artist_tag = live_tags[0]
        artist_name = str(
            (artist_details.get(artist_slug) or {}).get("name")
            or artist_tag
        )
        defaults_path = resolve_local_path(
            config_root,
            str(current_config()["paths"]["artist_descriptions"]),
        )
        defaults = _artist_defaults(defaults_path, artist_tag)
        description = str(
            defaults.get("description") or defaults.get("bio") or ""
        ).strip()
        attributes = deepcopy(defaults.get("default_attributes") or {})
        if not isinstance(attributes, dict):
            raise ValueError("Artist default_attributes must be an object")
        instagram = str(
            (artist_details.get(artist_slug) or {}).get("instagram_url") or ""
        )
        if instagram:
            attributes.setdefault("press,_media,_blog_link", instagram)

        latitude = selected.get("latitude")
        longitude = selected.get("longitude")
        if latitude is None or longitude is None:
            latitude = cluster.get("latitude")
            longitude = cluster.get("longitude")
        nonce = secrets.token_urlsafe(24)
        pending[nonce] = {
            "created_at": now,
            "run_id": run_id,
            "cluster_id": cluster_id,
            "photos": {
                path: asdict(FileFingerprint.from_path(Path(path)))
                for path in allowed
            },
        }
        while len(pending) > 50:
            pending.pop(next(iter(pending)))

        token = state["sac_oauth_token"]
        scopes = (
            set(str(token.get("scope") or "").split())
            if token and float(token["expires_at"]) > now else set()
        )
        connected = bool(token and SAC_REQUIRED_PROPOSAL_SCOPES <= scopes)
        report = manager.report(run_id)
        return render_template(
            "sac_proposal.html",
            proposal_token=nonce,
            run_id=run_id,
            cluster=cluster,
            photos=photos,
            selected_path=selected_path,
            city=str(report.get("city") or ""),
            latitude=latitude,
            longitude=longitude,
            artist_slug=artist_slug,
            artist_name=artist_name,
            description=description,
            attributes=[
                (key, json.dumps(value, ensure_ascii=False))
                for key, value in attributes.items()
            ],
            connected=connected,
            granted_scopes=sorted(scopes),
            read_only=bool(current_config().get("read_only")),
        )

    @app.post("/api/sac/proposals/submit")
    def submit_sac_proposal():
        if not _is_local_request():
            abort(403)
        if current_config().get("read_only"):
            abort(403)
        payload = request.get_json(force=True)
        nonce = str(payload.get("proposal_token") or "")
        proposal = state["sac_proposals"].get(nonce)
        if proposal is None:
            raise ValueError("Unknown or expired Street Art Cities proposal")
        if (
            time.time() - float(proposal["created_at"])
            > SAC_PROPOSAL_PENDING_SECONDS
        ):
            state["sac_proposals"].pop(nonce, None)
            raise ValueError("Street Art Cities proposal expired; reopen it")

        token = state["sac_oauth_token"]
        if token is None or float(token["expires_at"]) <= time.time():
            raise ValueError("Connect Street Art Cities before confirming")
        scopes = set(str(token.get("scope") or "").split())
        missing_scopes = sorted(SAC_REQUIRED_PROPOSAL_SCOPES - scopes)
        if missing_scopes:
            raise ValueError(
                "Reconnect Street Art Cities to grant: "
                + ", ".join(missing_scopes)
            )

        requested_photos = payload.get("photos")
        if not isinstance(requested_photos, list) or not requested_photos:
            raise ValueError("Select at least one image")
        if len(requested_photos) > 10:
            raise ValueError("Select at most 10 images")
        selected_paths: list[Path] = []
        seen_paths: set[str] = set()
        for value in requested_photos:
            path = Path(str(value)).resolve()
            key = str(path)
            expected = proposal["photos"].get(key)
            if expected is None or key in seen_paths:
                raise ValueError("Selected image is outside this proposal")
            if asdict(FileFingerprint.from_path(path)) != expected:
                raise ValueError(f"Selected image changed after preview: {path}")
            if not _inside(path, source_roots()):
                raise ValueError("Selected image is outside configured sources")
            selected_paths.append(path)
            seen_paths.add(key)

        city = str(payload.get("city") or "").strip()
        if not CITY_SLUG_RE.fullmatch(city):
            raise ValueError("Street Art Cities city must be a lowercase slug")
        try:
            latitude = float(payload["latitude"])
            longitude = float(payload["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Valid latitude and longitude are required") from exc
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("Latitude or longitude is outside its valid range")

        artists = payload.get("artists")
        if not isinstance(artists, list):
            raise ValueError("Artists must be a list")
        artist_actions: list[dict[str, str]] = []
        for artist in artists:
            if not isinstance(artist, dict):
                raise ValueError("Each artist must be an object")
            artist_id = str(artist.get("id") or "").strip()
            title = str(artist.get("title") or "").strip()
            if artist_id and title:
                raise ValueError("Use either an artist ID or a new artist name")
            if artist_id:
                if not ARTIST_SLUG_RE.fullmatch(artist_id):
                    raise ValueError(f"Invalid artist ID: {artist_id}")
                artist_actions.append({"id": artist_id})
            elif title:
                if len(title) > 200:
                    raise ValueError("Artist names must be at most 200 characters")
                artist_actions.append({"title": title})

        tags = payload.get("tags")
        if not isinstance(tags, list) or any(
            not isinstance(tag, str) for tag in tags
        ):
            raise ValueError("Tags must be a list of text values")
        clean_tags = list(dict.fromkeys(
            tag.strip() for tag in tags if tag.strip()
        ))
        attributes = payload.get("attributes")
        if not isinstance(attributes, dict):
            raise ValueError("Advanced attributes must be an object")
        action_attributes: dict[str, Any] = {}
        for key, value in attributes.items():
            clean_key = str(key).strip()
            if (
                not clean_key
                or "." in clean_key
                or len(clean_key) > 100
                or value in (None, "", [])
            ):
                if value in (None, "", []):
                    continue
                raise ValueError(f"Invalid advanced attribute: {clean_key}")
            action_attributes[f"attributes.{clean_key}"] = value

        title = str(payload.get("title") or "").strip()
        description = str(payload.get("description") or "").strip()
        attribution = str(payload.get("attribution") or "").strip()
        edit_comment = str(payload.get("edit_comment") or "").strip()
        if len(title) > 500 or len(description) > 20_000:
            raise ValueError("Title or description is too long")
        actions: dict[str, Any] = {
            "lat": latitude,
            "lng": longitude,
            "city": city,
            "type": "artwork",
            "artists": artist_actions,
            **action_attributes,
        }
        if title:
            actions["title"] = title
        if description:
            actions["description"] = description
        if clean_tags:
            actions["tags"] = clean_tags

        approved = {
            "photos": [str(path) for path in selected_paths],
            "fingerprints": {
                str(path): proposal["photos"][str(path)]
                for path in selected_paths
            },
            "actions": actions,
            "attribution": attribution,
            "edit_comment": edit_comment,
        }
        signature = hashlib.sha256(json.dumps(
            approved,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")).hexdigest()
        receipt_id = f"sac-create-{nonce}"
        receipt_file = plan_path(receipt_id)
        if receipt_file.is_file():
            receipt = _load_json(receipt_file)
            if receipt.get("signature") != signature:
                if receipt.get("images"):
                    raise ValueError(
                        "The form changed after an image upload; reopen the "
                        "proposal before retrying"
                    )
                receipt = {}
        else:
            receipt = {}
        if not receipt:
            receipt = {
                "version": 1,
                "id": receipt_id,
                "kind": "sac-marker-creation",
                "created_at": datetime.now().astimezone().isoformat(),
                "state": "uploading",
                "signature": signature,
                "approved": approved,
                "images": [],
            }
            save_plan(receipt)

        uploaded_by_path = {
            item["path"]: item for item in receipt.get("images") or []
        }
        marker_images: list[dict[str, Any]] = []
        access_token = str(token["access_token"])
        for path in selected_paths:
            existing = uploaded_by_path.get(str(path))
            if existing:
                marker_images.append(existing["image"])
                continue
            content_type = _photo_content_type(path)
            try:
                upload = request_media_upload(
                    access_token,
                    filename=path.name,
                    content_type=content_type,
                )
            except SACAuthorizationError as exc:
                state["sac_oauth_token"] = None
                raise ValueError(
                    f"{exc}. Reconnect the API and retry this proposal; "
                    "completed image uploads are saved."
                ) from exc
            upload_media_file(
                path,
                upload["url"],
                content_type=content_type,
            )
            image = _uploaded_image(
                upload["publicUrl"],
                attribution=attribution,
            )
            receipt["images"].append({
                "path": str(path),
                "public_url": upload["publicUrl"],
                "image": image,
                "uploaded_at": datetime.now().astimezone().isoformat(),
            })
            save_plan(receipt)
            marker_images.append(image)

        actions["images"] = marker_images
        try:
            edit = submit_marker_creation(
                access_token,
                actions,
                edit_comment=edit_comment,
            )
        except SACAuthorizationError as exc:
            state["sac_oauth_token"] = None
            raise ValueError(
                f"{exc}. Reconnect the API and retry this proposal; completed "
                "image uploads are saved."
            ) from exc
        receipt["state"] = "submitted"
        receipt["edit"] = edit
        receipt["completed_at"] = datetime.now().astimezone().isoformat()
        save_plan(receipt)
        state["sac_proposals"].pop(nonce, None)
        return jsonify({
            "ok": True,
            "edit": edit,
            "receipt": str(receipt_file),
        })

    @app.post("/api/runs/<run_id>/clusters/<cluster_id>/tags/preview")
    def tag_preview(run_id: str, cluster_id: str):
        cluster = report_cluster(run_id, cluster_id)
        payload = request.get_json(force=True)
        allowed = cluster_paths(cluster)
        requested = payload.get("paths")
        if requested is None:
            paths = allowed
        else:
            requested_paths = [Path(path).resolve() for path in requested]
            if any(path not in allowed for path in requested_paths):
                raise ValueError("Selected photo is outside this cluster")
            paths = requested_paths
        if not paths:
            raise ValueError("Select at least one cluster photo")
        plan = build_tag_edit_plan(
            paths,
            add=payload.get("add") or [],
            remove=payload.get("remove") or [],
        )
        plan["run_id"] = run_id
        plan["cluster_id"] = cluster_id
        save_plan(plan)
        return jsonify({"ok": True, "plan": plan})

    @app.post("/api/runs/<run_id>/clusters/<cluster_id>/gps/preview")
    def manual_gps_preview(run_id: str, cluster_id: str):
        cluster = report_cluster(run_id, cluster_id)
        payload = request.get_json(force=True)
        allowed_items = {
            str(Path(item["path"]).resolve()): item
            for item in [*cluster["photos"], *cluster["context_photos"]]
        }
        moves = payload.get("moves")
        if moves is not None:
            if not isinstance(moves, list):
                raise ValueError("GPS moves must be a list")
            planned = []
            seen = set()
            for move in moves:
                if not isinstance(move, dict):
                    raise ValueError("Each GPS move must be an object")
                path = str(Path(str(move.get("path") or "")).resolve())
                if path not in allowed_items:
                    raise ValueError("Selected photo is outside this cluster")
                if path in seen:
                    raise ValueError("A photo can only have one GPS move")
                seen.add(path)
                item = allowed_items[path]
                planned.append((
                    read_photo(Path(path), str(item.get("source") or "")),
                    float(move["latitude"]),
                    float(move["longitude"]),
                ))
            plan = build_individual_gps_plan(planned)
            plan["run_id"] = run_id
            plan["cluster_id"] = cluster_id
            save_plan(plan)
            return jsonify({"ok": True, "plan": plan})
        requested_paths = payload.get("paths")
        selected_paths = (
            {
                str(Path(path).resolve())
                for path in requested_paths
            }
            if requested_paths is not None else None
        )
        photos = []
        for item in [*cluster["photos"], *cluster["context_photos"]]:
            path = Path(item["path"]).resolve()
            if selected_paths is None or str(path) in selected_paths:
                photos.append(read_photo(path, str(item.get("source") or "")))
        if not photos:
            raise ValueError("Select at least one cluster photo")
        plan = build_manual_gps_plan(
            photos,
            latitude=float(payload["latitude"]),
            longitude=float(payload["longitude"]),
        )
        plan["run_id"] = run_id
        plan["cluster_id"] = cluster_id
        save_plan(plan)
        return jsonify({"ok": True, "plan": plan})

    @app.get("/photo")
    def photo():
        path = Path(str(request.args.get("path") or "")).resolve()
        if not _inside(path, source_roots()) or not path.is_file():
            abort(404)
        return send_file(path)

    @app.get("/reference")
    def reference():
        path = Path(str(request.args.get("path") or "")).resolve()
        root = resolve_local_path(
            config_root,
            str(current_config()["paths"]["reference_images"]),
        )
        if not _inside(path, [root]) or not path.is_file():
            abort(404)
        return send_file(path)

    @app.get("/runs/<run_id>/clusters/<cluster_id>/next")
    def next_cluster(run_id: str, cluster_id: str):
        clusters = manager.report(run_id)["clusters"]
        ids = [cluster["id"] for cluster in clusters]
        if cluster_id not in ids:
            raise ValueError("Unknown cluster")
        next_id = ids[(ids.index(cluster_id) + 1) % len(ids)]
        return redirect(url_for(
            "cluster_review", run_id=run_id, cluster_id=next_id
        ))

    @app.get("/runs/<run_id>/clusters/<cluster_id>/previous")
    def previous_cluster(run_id: str, cluster_id: str):
        clusters = manager.report(run_id)["clusters"]
        ids = [cluster["id"] for cluster in clusters]
        if cluster_id not in ids:
            raise ValueError("Unknown cluster")
        previous_id = ids[(ids.index(cluster_id) - 1) % len(ids)]
        return redirect(url_for(
            "cluster_review", run_id=run_id, cluster_id=previous_id
        ))

    return app
