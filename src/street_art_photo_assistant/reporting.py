"""Offline cluster report persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from .models import PhotoCluster


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def write_cluster_report(
    clusters: Iterable[PhotoCluster],
    json_path: Path,
    markdown_path: Path,
) -> None:
    """Write review-compatible offline JSON and concise Markdown."""

    cluster_list = list(clusters)
    payload = {
        "mode": "cluster-only",
        "clusters": [cluster.to_dict() for cluster in cluster_list],
    }
    _atomic_text(
        json_path,
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )
    lines = [
        "# Street Art Photo Clusters",
        "",
        "Street Art Cities matching was disabled for this report.",
        "",
        f"Clusters: **{len(cluster_list)}**",
        "",
    ]
    for cluster in cluster_list:
        location = (
            f"{cluster.latitude:.6f}, {cluster.longitude:.6f}"
            if cluster.latitude is not None and cluster.longitude is not None
            else "no GPS"
        )
        lines.extend([
            f"## {cluster.tag} — {cluster.id}",
            "",
            f"- Location: {location}",
            f"- Primary photos: {len(cluster.photos)}",
            f"- Context photos: {len(cluster.context_photos)}",
            "",
        ])
    _atomic_text(markdown_path, "\n".join(lines))

