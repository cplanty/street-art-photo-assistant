"""Atomic JSON change logs for photo metadata writes."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_change_log(
    path: Path,
    *,
    operation: str,
    plan_id: str,
    changes: list[dict[str, Any]],
    status: str = "complete",
) -> None:
    """Write one complete operation log atomically."""

    payload = {
        "version": 1,
        "operation": operation,
        "plan_id": plan_id,
        "status": status,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "changes": changes,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    os.replace(temporary, path)
