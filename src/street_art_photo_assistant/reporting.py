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
    *,
    city: str | None = None,
    sac_evidence: dict[str, dict] | None = None,
) -> None:
    """Write review-compatible JSON and concise Markdown."""

    cluster_list = list(clusters)
    cluster_payloads = []
    for cluster in cluster_list:
        payload = cluster.to_dict()
        if sac_evidence is not None:
            payload["street_art_cities"] = sac_evidence.get(cluster.id)
        cluster_payloads.append(payload)
    payload = {
        "mode": "street-art-cities" if sac_evidence is not None else "cluster-only",
        "city": city,
        "clusters": cluster_payloads,
    }
    _atomic_text(
        json_path,
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )
    lines = [
        "# Street Art Photo Clusters",
        "",
        (
            f"Street Art Cities city: **{city}**"
            if sac_evidence is not None
            else "Street Art Cities matching was disabled for this report."
        ),
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
        ])
        if sac_evidence is not None:
            evidence = sac_evidence.get(cluster.id) or {}
            lines.extend([
                f"- SAC status: {evidence.get('status', 'unknown')}",
                f"- Recommendation: {evidence.get('recommendation', 'Review')}",
                f"- Nearby candidates: {len(evidence.get('candidates') or [])}",
            ])
        lines.append("")
    _atomic_text(markdown_path, "\n".join(lines))
