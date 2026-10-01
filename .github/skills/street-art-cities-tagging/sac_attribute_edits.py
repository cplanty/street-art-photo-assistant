from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import threading
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlencode, urlparse

import requests


BASE_URL = "https://streetartcities.com"
REDIRECT_URI = "http://127.0.0.1:8787/login"
PREVIEW_SCOPES = ("markers:read", "edits:read")
APPLY_SCOPES = ("markers:read", "edits:write", "edits:read")
PLAN_VERSION = 1
USER_AGENT = "StreetArtPhotoAssistant-SAC-Tagging-Skill/1"


@dataclass(frozen=True)
class OAuthResult:
    code: str
    state: str


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_client_id(explicit: str | None, config_path: Path) -> str:
    if explicit:
        return explicit
    config = load_json(config_path)
    matching = config.get("matching")
    if not isinstance(matching, dict):
        raise ValueError(f"{config_path} has no matching configuration")
    client_id = str(matching.get("api_client_id") or "").strip()
    if not client_id:
        raise ValueError(
            f"{config_path} has no matching.api_client_id; pass --client-id"
        )
    return client_id


def marker_id(value: str) -> str:
    candidate = value.strip().rstrip("/").rsplit("/", 1)[-1]
    if (
        len(candidate) != 36
        or candidate.count("-") != 4
        or any(char not in "0123456789abcdefABCDEF-" for char in candidate)
    ):
        raise ValueError(f"Invalid marker ID or URL: {value}")
    return candidate.lower()


def unique_values(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip()
        folded = value.casefold()
        if not value:
            raise ValueError("Attribute values cannot be blank")
        if folded not in seen:
            result.append(value)
            seen.add(folded)
    if not result:
        raise ValueError("At least one attribute value is required")
    return result


def normalize_existing(value: object, path: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise ValueError(f"{path} is not a string array")


def value_at_path(marker: dict[str, Any], path: str) -> object:
    value: object = marker
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def missing_values(existing: Iterable[str], desired: Iterable[str]) -> list[str]:
    existing_folded = {item.casefold() for item in existing}
    return [item for item in desired if item.casefold() not in existing_folded]


def matching_pending_edit_ids(
    edits: Iterable[object],
    marker_id_value: str,
    path: str,
    missing: Iterable[str],
) -> list[str]:
    required = {value.casefold() for value in missing}
    if not required:
        return []
    matches: list[str] = []
    for candidate in edits:
        if not isinstance(candidate, dict):
            continue
        if (
            candidate.get("status") != "submitted"
            or candidate.get("entityType") != "marker"
            or candidate.get("entityId") != marker_id_value
        ):
            continue
        actions = candidate.get("actions")
        if not isinstance(actions, dict):
            continue
        action = actions.get(path)
        if isinstance(action, dict):
            added = action.get("$add")
        else:
            added = action
        if not isinstance(added, list) or not all(
            isinstance(value, str) for value in added
        ):
            continue
        if required.issubset({value.casefold() for value in added}):
            edit_id = str(candidate.get("id") or "")
            if edit_id:
                matches.append(edit_id)
    return matches


class CallbackHandler(BaseHTTPRequestHandler):
    result: OAuthResult | None = None
    expected_state = ""
    error: str | None = None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path != "/login":
            self.send_error(404)
            return

        returned_state = query.get("state", [""])[0]
        code = query.get("code", [""])[0]
        oauth_error = query.get("error", [""])[0]
        if oauth_error:
            type(self).error = f"Authorization failed: {oauth_error}"
        elif returned_state != type(self).expected_state:
            type(self).error = "OAuth state validation failed"
        elif not code:
            type(self).error = "Authorization returned no code"
        else:
            type(self).result = OAuthResult(code=code, state=returned_state)

        ok = type(self).result is not None
        message = (
            "Street Art Cities authorization completed. You may close this tab."
            if ok
            else "Street Art Cities authorization failed. You may close this tab."
        )
        encoded = message.encode("utf-8")
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, format: str, *args: object) -> None:
        return


def authorize(client_id: str, scopes: Iterable[str]) -> str:
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    authorization_url = BASE_URL + "/api/oauth/authorize?" + urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )

    CallbackHandler.result = None
    CallbackHandler.error = None
    CallbackHandler.expected_state = state
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 8787), CallbackHandler)
    except OSError as exc:
        raise RuntimeError(
            "Cannot start the OAuth callback on 127.0.0.1:8787"
        ) from exc

    print("Opening Street Art Cities authorization in the default browser.")
    if not webbrowser.open(authorization_url):
        server.server_close()
        raise RuntimeError(
            "Could not open the default browser for SAC authorization"
        )
    server.serve_forever()
    server.server_close()
    if CallbackHandler.error:
        raise RuntimeError(CallbackHandler.error)
    if CallbackHandler.result is None:
        raise RuntimeError("OAuth callback completed without a result")

    response = requests.post(
        BASE_URL + "/api/oauth/token",
        json={
            "grant_type": "authorization_code",
            "code": CallbackHandler.result.code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    token = str(payload.get("access_token") or "")
    if not token:
        raise ValueError("Street Art Cities returned no access token")
    return token


def api_request(
    method: str,
    path: str,
    token: str,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = requests.request(
        method,
        BASE_URL + path,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
        },
        json=payload,
        timeout=30,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = response.text[:500]
        raise RuntimeError(
            f"SAC {method} {path} failed with {response.status_code}: {detail}"
        ) from exc
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError(f"SAC {method} {path} returned no JSON object")
    return result


def preview(args: argparse.Namespace) -> None:
    output = Path(args.output).resolve()
    if output.exists() and not args.replace:
        raise FileExistsError(f"Plan already exists: {output}")
    client_id = load_client_id(args.client_id, Path(args.config))
    path = args.path.strip()
    if not path.startswith("attributes.") or path.count(".") != 1:
        raise ValueError("--path must be attributes.<attribute-name>")
    desired = unique_values(args.value)
    marker_ids = list(dict.fromkeys(marker_id(value) for value in args.marker))
    token = authorize(client_id, PREVIEW_SCOPES)
    edits: list[object] = []
    for edit_id in dict.fromkeys(args.known_edit_id):
        response = api_request("GET", f"/api/edits/{edit_id}", token)
        edit = response.get("edit")
        if not isinstance(edit, dict):
            raise ValueError(f"SAC returned no edit for {edit_id}")
        edits.append(edit)

    targets: list[dict[str, Any]] = []
    for target_id in marker_ids:
        marker = api_request("GET", f"/api/markers/{target_id}", token)
        existing = normalize_existing(value_at_path(marker, path), path)
        missing = missing_values(existing, desired)
        targets.append(
            {
                "marker_id": target_id,
                "updated_at": marker.get("updatedAt"),
                "existing": existing,
                "missing": missing,
                "pending_edit_ids": matching_pending_edit_ids(
                    edits,
                    target_id,
                    path,
                    missing,
                ),
            }
        )

    plan = {
        "version": PLAN_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "path": path,
        "values": desired,
        "targets": targets,
    }
    atomic_write_json(output, plan)
    pending = sum(bool(target["pending_edit_ids"]) for target in targets)
    proposed = sum(
        bool(target["missing"]) and not target["pending_edit_ids"]
        for target in targets
    )
    no_op = len(targets) - proposed - pending
    print(f"Plan: {output}")
    print(
        f"Targets: {len(targets)}; proposed edits: {proposed}; "
        f"matching pending: {pending}; no-ops: {no_op}"
    )
    for target in targets:
        if target["pending_edit_ids"]:
            status = "already pending " + ", ".join(target["pending_edit_ids"])
        elif target["missing"]:
            status = "add " + json.dumps(target["missing"], ensure_ascii=False)
        else:
            status = "no-op"
        print(f"- {target['marker_id']}: {status}")


def validate_plan(plan: dict[str, Any]) -> tuple[str, list[str], list[dict[str, Any]]]:
    if plan.get("version") != PLAN_VERSION:
        raise ValueError("Unsupported plan version")
    path = plan.get("path")
    values = plan.get("values")
    targets = plan.get("targets")
    if not isinstance(path, str) or not path.startswith("attributes."):
        raise ValueError("Plan has no valid attribute path")
    if not isinstance(values, list) or not all(
        isinstance(value, str) and value for value in values
    ):
        raise ValueError("Plan has no valid values")
    if not isinstance(targets, list) or not all(
        isinstance(target, dict) for target in targets
    ):
        raise ValueError("Plan has no valid targets")
    return path, values, targets


def validate_scalar_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    if plan.get("version") != PLAN_VERSION:
        raise ValueError("Unsupported scalar plan version")
    targets = plan.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("Scalar plan has no targets")
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("Scalar plan has an invalid target")
        actions = target.get("actions")
        current = target.get("current")
        if not isinstance(actions, dict) or not actions:
            raise ValueError("Scalar plan target has no actions")
        if not isinstance(current, dict):
            raise ValueError("Scalar plan target has no current values")
        for path, value in actions.items():
            if (
                not isinstance(path, str)
                or not path.startswith("attributes.")
                or not isinstance(value, str)
                or not value
            ):
                raise ValueError("Scalar actions must set non-empty attributes")
            if path not in current:
                raise ValueError(f"Scalar plan has no current value for {path}")
            if current[path] not in (None, ""):
                raise ValueError(f"Scalar plan would overwrite non-empty {path}")
    return targets


def apply_scalar_plan(
    args: argparse.Namespace,
    plan_path: Path,
    plan: dict[str, Any],
) -> None:
    targets = validate_scalar_plan(plan)
    receipt_path = (
        Path(args.receipt).resolve()
        if args.receipt
        else plan_path.with_name(plan_path.stem + ".receipt.json")
    )
    if receipt_path.exists():
        if not args.resume:
            raise FileExistsError(
                f"Receipt already exists: {receipt_path}; use --resume only "
                "after checking a partial receipt"
            )
        receipt = load_json(receipt_path)
    else:
        receipt = {
            "version": 1,
            "plan": str(plan_path),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "state": "in_progress",
            "results": [],
        }
        atomic_write_json(receipt_path, receipt)

    results = receipt.get("results")
    if not isinstance(results, list):
        raise ValueError("Receipt has no valid results list")
    completed = {
        result.get("marker_id")
        for result in results
        if isinstance(result, dict) and result.get("edit_id")
    }
    remaining = [
        target for target in targets if target.get("marker_id") not in completed
    ]
    if not remaining:
        receipt["state"] = "complete"
        atomic_write_json(receipt_path, receipt)
        print(f"Nothing left to submit; receipt is complete: {receipt_path}")
        return

    client_id = load_client_id(args.client_id, Path(args.config))
    token = authorize(client_id, APPLY_SCOPES)
    for target in remaining:
        target_id = str(target.get("marker_id") or "")
        marker = api_request("GET", f"/api/markers/{target_id}", token)
        if marker.get("updatedAt") != target.get("updated_at"):
            raise RuntimeError(f"Stale plan: marker {target_id} was updated")
        actions = target["actions"]
        for path, expected in target["current"].items():
            actual = value_at_path(marker, path)
            if actual != expected:
                raise RuntimeError(
                    f"Stale plan: {path} changed on marker {target_id}"
                )
        if set(actions) != set(target["current"]):
            raise ValueError(f"Scalar plan paths differ for marker {target_id}")

    try:
        for target in remaining:
            target_id = str(target["marker_id"])
            actions = target["actions"]
            created = api_request(
                "POST",
                "/api/edits",
                token,
                payload={
                    "entityType": "marker",
                    "entityId": target_id,
                    "actions": actions,
                    "editComment": args.comment,
                },
            )
            edit = created.get("edit")
            if not isinstance(edit, dict) or not edit.get("id"):
                raise ValueError("SAC returned no created edit")
            edit_id = str(edit["id"])
            verified = api_request("GET", f"/api/edits/{edit_id}", token)
            changes = verified.get("changes")
            changed_paths = {
                change.get("path")
                for change in changes
                if isinstance(change, dict)
            } if isinstance(changes, list) else set()
            if not set(actions).issubset(changed_paths):
                raise RuntimeError(
                    f"SAC edit {edit_id} does not contain every approved path"
                )
            results.append(
                {
                    "marker_id": target_id,
                    "outcome": "submitted",
                    "actions": actions,
                    "edit_id": edit_id,
                    "status": edit.get("status"),
                    "reviewable": verified.get("reviewable") is True,
                    "review_url": edit.get("reviewUrl"),
                }
            )
            atomic_write_json(receipt_path, receipt)
    except Exception as exc:
        receipt["state"] = "partial"
        receipt["error"] = str(exc)
        atomic_write_json(receipt_path, receipt)
        raise

    receipt["state"] = "complete"
    receipt["completed_at"] = datetime.now(timezone.utc).isoformat()
    receipt.pop("error", None)
    atomic_write_json(receipt_path, receipt)
    print(f"Receipt: {receipt_path}")
    for result in results:
        if isinstance(result, dict):
            print(
                f"- {result.get('marker_id')}: {result.get('status')} "
                f"{result.get('review_url') or ''}".rstrip()
            )


def apply(args: argparse.Namespace) -> None:
    plan_path = Path(args.plan).resolve()
    plan = load_json(plan_path)
    if plan.get("kind") == "scalar-actions":
        apply_scalar_plan(args, plan_path, plan)
        return
    path, values, targets = validate_plan(plan)
    receipt_path = (
        Path(args.receipt).resolve()
        if args.receipt
        else plan_path.with_name(plan_path.stem + ".receipt.json")
    )
    if receipt_path.exists():
        if not args.resume:
            raise FileExistsError(
                f"Receipt already exists: {receipt_path}; use --resume only "
                "after checking a partial receipt"
            )
        receipt = load_json(receipt_path)
    else:
        receipt = {
            "version": 1,
            "plan": str(plan_path),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "state": "in_progress",
            "results": [],
        }
        atomic_write_json(receipt_path, receipt)

    results = receipt.get("results")
    if not isinstance(results, list):
        raise ValueError("Receipt has no valid results list")
    completed = {
        result.get("marker_id")
        for result in results
        if isinstance(result, dict) and result.get("edit_id")
    }
    remaining = [
        target for target in targets if target.get("marker_id") not in completed
    ]
    if not remaining:
        receipt["state"] = "complete"
        atomic_write_json(receipt_path, receipt)
        print(f"Nothing left to submit; receipt is complete: {receipt_path}")
        return

    client_id = load_client_id(args.client_id, Path(args.config))
    scopes = list(APPLY_SCOPES)
    token = authorize(client_id, scopes)

    for target in remaining:
        target_id = str(target.get("marker_id") or "")
        marker = api_request("GET", f"/api/markers/{target_id}", token)
        existing = normalize_existing(value_at_path(marker, path), path)
        if marker.get("updatedAt") != target.get("updated_at"):
            raise RuntimeError(f"Stale plan: marker {target_id} was updated")
        if existing != target.get("existing"):
            raise RuntimeError(
                f"Stale plan: {path} changed on marker {target_id}"
            )
        expected_missing = missing_values(existing, values)
        if expected_missing != target.get("missing"):
            raise RuntimeError(
                f"Stale plan: proposed values changed for marker {target_id}"
            )

    try:
        for target in remaining:
            target_id = str(target["marker_id"])
            missing = target.get("missing")
            if not isinstance(missing, list):
                raise ValueError(f"Plan has invalid missing values for {target_id}")
            pending_edit_ids = target.get("pending_edit_ids")
            if not isinstance(pending_edit_ids, list):
                raise ValueError(
                    f"Plan has invalid pending edit IDs for {target_id}"
                )
            if pending_edit_ids:
                results.append(
                    {
                        "marker_id": target_id,
                        "outcome": "pending",
                        "pending_edit_ids": pending_edit_ids,
                    }
                )
                atomic_write_json(receipt_path, receipt)
                continue
            if not missing:
                results.append(
                    {
                        "marker_id": target_id,
                        "outcome": "no-op",
                    }
                )
                atomic_write_json(receipt_path, receipt)
                continue

            created = api_request(
                "POST",
                "/api/edits",
                token,
                payload={
                    "entityType": "marker",
                    "entityId": target_id,
                    "actions": {path: {"$add": missing}},
                    "editComment": args.comment,
                },
            )
            edit = created.get("edit")
            if not isinstance(edit, dict) or not edit.get("id"):
                raise ValueError("SAC returned no created edit")
            edit_id = str(edit["id"])
            verified = api_request("GET", f"/api/edits/{edit_id}", token)
            status = str(edit.get("status") or "")
            reviewable = verified.get("reviewable") is True

            results.append(
                {
                    "marker_id": target_id,
                    "outcome": "submitted",
                    "added": missing,
                    "edit_id": edit_id,
                    "status": status,
                    "reviewable": reviewable,
                    "review_url": edit.get("reviewUrl"),
                }
            )
            atomic_write_json(receipt_path, receipt)
    except Exception as exc:
        receipt["state"] = "partial"
        receipt["error"] = str(exc)
        atomic_write_json(receipt_path, receipt)
        raise

    receipt["state"] = "complete"
    receipt["completed_at"] = datetime.now(timezone.utc).isoformat()
    receipt.pop("error", None)
    atomic_write_json(receipt_path, receipt)
    print(f"Receipt: {receipt_path}")
    for result in results:
        if not isinstance(result, dict):
            continue
        print(
            f"- {result.get('marker_id')}: {result.get('status', 'no-op')} "
            f"{result.get('review_url') or ''}".rstrip()
        )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Preview and submit SAC marker attribute edits."
    )
    root.add_argument(
        "--config",
        default="config.local.json",
        help="Config containing matching.api_client_id.",
    )
    root.add_argument("--client-id", help="Override the OAuth client ID.")
    commands = root.add_subparsers(dest="command", required=True)

    preview_parser = commands.add_parser("preview")
    preview_parser.add_argument("--path", required=True)
    preview_parser.add_argument("--value", action="append", required=True)
    preview_parser.add_argument("--marker", action="append", required=True)
    preview_parser.add_argument(
        "--known-edit-id",
        action="append",
        default=[],
        help="Pending edit ID to verify and avoid submitting twice.",
    )
    preview_parser.add_argument("--output", required=True)
    preview_parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing plan file.",
    )
    preview_parser.set_defaults(run=preview)

    apply_parser = commands.add_parser("apply")
    apply_parser.add_argument("--plan", required=True)
    apply_parser.add_argument("--receipt")
    apply_parser.add_argument(
        "--comment",
        default="Add reviewed marker attribute tags.",
    )
    apply_parser.add_argument("--resume", action="store_true")
    apply_parser.set_defaults(run=apply)
    return root


def main() -> None:
    args = parser().parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
