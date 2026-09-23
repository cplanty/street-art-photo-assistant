"""Local Flask application for generation and cluster review."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from .config import resolve_local_path, save_config, validate_config
from .gps import apply_gps_plan, build_manual_gps_plan, build_missing_gps_plan
from .metadata import apply_tag_edit_plan, build_tag_edit_plan
from .models import PhotoRecord
from .photos import read_photo
from .runs import RunManager
from .workflow import scan_and_select, sources_from_config


def _signature(config: dict[str, Any]) -> str:
    encoded = json.dumps(
        config, sort_keys=True, separators=(",", ":"), ensure_ascii=False
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


def _choose_folder(initial: str) -> str:
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as exc:
        raise RuntimeError("The native folder requester is unavailable") from exc
    root = tkinter.Tk()
    root.withdraw()
    try:
        return filedialog.askdirectory(
            initialdir=initial if Path(initial).is_dir() else None,
            mustexist=True,
        )
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
    }
    runs_path = resolve_local_path(
        config_root, str(config["paths"]["runs"])
    )
    manager = run_manager or RunManager(runs_path)
    plan_root = manager.run_root / "_plans"
    plan_root.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__)
    app.config["ASSISTANT_STATE"] = state
    app.config["ASSISTANT_CONFIG_PATH"] = config_path
    app.config["RUN_MANAGER"] = manager

    def current_config() -> dict[str, Any]:
        return state["config"]

    def source_roots() -> list[Path]:
        return [
            source.path.resolve()
            for source in sources_from_config(current_config(), config_root)
            if source.enabled
        ]

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
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": str(exc)}), 400
        return str(exc), 400

    @app.errorhandler(OSError)
    def os_error(exc: OSError):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": str(exc)}), 500
        return str(exc), 500

    @app.errorhandler(RuntimeError)
    def runtime_error(exc: RuntimeError):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": str(exc)}), 500
        return str(exc), 500

    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html",
            config=current_config(),
            config_path=config_path,
            artists_path=resolve_local_path(
                config_root, str(current_config()["paths"]["artists"])
            ),
            runs=manager.list_runs(),
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/config")
    def update_config():
        payload = request.get_json(force=True)
        if not isinstance(payload, dict):
            raise ValueError("Configuration must be an object")
        validate_config(payload)
        save_config(config_path, payload)
        state["config"] = deepcopy(payload)
        return jsonify({"ok": True})

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
            path = resolve_local_path(
                config_root, str(current_config()["paths"]["artists"])
            )
        else:
            candidate = Path(target).resolve()
            if not _inside(candidate, source_roots()):
                raise ValueError("Local path is outside configured sources")
            path = candidate
        if not path.exists():
            raise ValueError(f"Local path does not exist: {path}")
        if not hasattr(os, "startfile"):
            raise RuntimeError("Opening local files is supported on Windows")
        os.startfile(os.path.normpath(path))  # type: ignore[attr-defined]
        return jsonify({"ok": True})

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
        visual = bool(run_config["matching"].get("visual_enabled", False))
        return jsonify({"ok": True, "run": manager.start(
            run_config, visual=visual
        )})

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
        report = manager.report(run_id)
        return render_template(
            "run.html",
            manifest=manifest,
            clusters=report["clusters"],
        )

    @app.get("/runs/<run_id>/clusters/<cluster_id>")
    def cluster_review(run_id: str, cluster_id: str):
        cluster = refreshed_cluster(run_id, cluster_id)
        return render_template(
            "cluster.html",
            run_id=run_id,
            cluster=cluster,
            read_only=bool(current_config().get("read_only")),
        )

    @app.post("/api/runs/<run_id>/clusters/<cluster_id>/tags/preview")
    def tag_preview(run_id: str, cluster_id: str):
        cluster = report_cluster(run_id, cluster_id)
        payload = request.get_json(force=True)
        paths = [
            Path(photo["path"])
            for photo in [*cluster["photos"], *cluster["context_photos"]]
        ]
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
        selected_paths = {
            str(Path(path).resolve()) for path in payload.get("paths") or []
        }
        photos = []
        for item in [*cluster["photos"], *cluster["context_photos"]]:
            path = Path(item["path"]).resolve()
            if not selected_paths or str(path) in selected_paths:
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

    return app
