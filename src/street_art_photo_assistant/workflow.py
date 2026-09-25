"""Application-level offline selection and clustering workflow."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import date, datetime, time, timezone
from pathlib import Path
from time import sleep
from typing import Any

from .clustering import SelectionCriteria, cluster_photos, select_photos
from .matching import visual_subcluster
from .models import PhotoSource
from .photos import scan_sources
from .reporting import write_cluster_report


class ProgressReporter:
    """Persist structured progress for CLI, web polling, and diagnostics."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.warnings: list[str] = []

    def update(
        self,
        *,
        stage: str,
        percent: float,
        message: str,
        current: int | None = None,
        total: int | None = None,
        warning: str | None = None,
    ) -> None:
        new_warning = bool(warning and warning not in self.warnings)
        if new_warning and warning:
            self.warnings.append(warning)
        _atomic_json(self.path, {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "percent": max(0, min(100, round(percent, 1))),
            "message": message,
            "current": current,
            "total": total,
            "warnings": self.warnings,
        })
        count = (
            f" ({current}/{total})"
            if current is not None and total is not None else ""
        )
        print(
            f"[{percent:5.1f}%] {stage}: {message}{count}",
            flush=True,
        )
        if new_warning and warning:
            print(f"WARNING: {warning}", flush=True)


def _optional_date(value: object) -> date | None:
    text = str(value or "").strip()
    return date.fromisoformat(text) if text else None


def _optional_time(value: object) -> time | None:
    text = str(value or "").strip()
    return time.fromisoformat(text) if text else None


def _resolve(base: Path, value: object) -> Path:
    path = Path(str(value or "")).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    for attempt in range(5):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 4:
                raise
            sleep(0.02 * (attempt + 1))


def sources_from_config(
    config: dict[str, Any],
    config_root: Path,
) -> list[PhotoSource]:
    """Resolve configured source paths against the configuration directory."""

    return [
        PhotoSource(
            name=str(item["name"]),
            path=_resolve(config_root, item["path"]),
            enabled=item.get("enabled", True) is not False,
            gps_target=bool(item.get("gps_target", False)),
            gps_reference=bool(item.get("gps_reference", False)),
        )
        for item in config["sources"]
    ]


def selection_from_config(config: dict[str, Any]) -> SelectionCriteria:
    """Build typed selection criteria from the JSON contract."""

    selection = config["selection"]
    return SelectionCriteria(
        start=_optional_date(selection.get("start")),
        end=_optional_date(selection.get("end")),
        start_time=_optional_time(selection.get("start_time")),
        end_time=_optional_time(selection.get("end_time")),
        tagged_mode=str(selection["tagged_mode"]),
        include_tags=tuple(selection.get("include_tags") or []),
        exclude_tags=tuple(selection.get("exclude_tags") or []),
        missing_gps=str(selection["missing_gps"]),
    )


def scan_and_select(
    config: dict[str, Any],
    config_root: Path,
) -> tuple[list, list, object]:
    """Scan configured sources and apply the exact configured selection."""

    scanned = scan_sources(sources_from_config(config, config_root))
    selected, preview = select_photos(
        scanned, selection_from_config(config)
    )
    return scanned, selected, preview


def run_offline_clustering(
    config: dict[str, Any],
    *,
    config_root: Path,
    output_directory: Path,
    visual: bool = False,
) -> dict[str, Any]:
    """Run the complete network-free preview and clustering workflow."""

    output_directory.mkdir(parents=True, exist_ok=True)
    progress = ProgressReporter(output_directory / "progress.json")
    progress.update(
        stage="scanning",
        percent=5,
        message="Reading photo metadata from configured sources",
    )
    _scanned, selected, preview = scan_and_select(config, config_root)
    progress.update(
        stage="selection",
        percent=25,
        message=(
            f"Selected {preview.selected} of {preview.scanned} scanned photos"
        ),
        current=preview.selected,
        total=preview.scanned,
    )
    clustering = config["clustering"]
    progress.update(
        stage="clustering",
        percent=35,
        message="Grouping selected photos by tag and location",
    )
    clusters = cluster_photos(
        selected,
        radius_m=float(clustering["radius_m"]),
        generic_tags=clustering.get("generic_tags") or [],
        context_only_tags=clustering.get("context_only_tags") or [],
        unknown_tag=str(clustering["unknown_tag"]),
        wall_tag=str(clustering["wall_tag"]),
    )
    if visual:
        progress.update(
            stage="local-visual",
            percent=42,
            message=f"Visually checking {len(clusters)} local cluster(s)",
            current=0,
            total=len(clusters),
        )
        clusters = visual_subcluster(clusters)

    progress.update(
        stage="clustered",
        percent=50,
        message=f"Created {len(clusters)} cluster(s)",
        current=len(clusters),
        total=len(clusters),
    )
    _atomic_json(output_directory / "preview.json", asdict(preview))
    matching = config["matching"]
    city = None
    evidence = None
    if matching.get("street_art_cities_enabled"):
        from .sac import (
            USER_AGENT,
            RequestThrottle,
            cache_city_images,
            compare_clusters,
            refresh_city,
            refresh_city_api,
        )

        city = str(matching.get("city") or "").strip().lower()
        paths = config["paths"]
        throttle = RequestThrottle(
            float(matching["request_interval_seconds"])
        )
        marker_source = str(
            matching.get("marker_source") or "public-city-endpoint"
        )
        progress.update(
            stage="sac-refresh",
            percent=55,
            message=(
                f"Refreshing Street Art Cities markers for {city} via "
                f"{marker_source} "
                f"with User-Agent: {USER_AGENT}"
            ),
        )
        if marker_source == "oauth-markers-api":
            access_token = os.environ.get("SAC_API_ACCESS_TOKEN", "")
            if not access_token:
                raise RuntimeError(
                    "Connect the Street Art Cities API before using "
                    "the authenticated marker source"
                )
            city_payload = refresh_city_api(
                city,
                _resolve(config_root, paths["city_cache"]),
                access_token=access_token,
                throttle=throttle,
            )
        else:
            city_payload = refresh_city(
                city,
                _resolve(config_root, paths["city_cache"]),
                throttle=throttle,
            )
        marker_count = len(city_payload["markers"])
        marker_warning = None
        if marker_count >= int(
            matching["large_city_warning_markers"]
        ):
            marker_warning = (
                f"Large city catalogue: {marker_count} markers were returned "
                "by the selected marker source; local comparison may take time."
            )
        progress.update(
            stage="sac-matching",
            percent=65,
            message=(
                f"Comparing {len(clusters)} cluster(s) with "
                f"{marker_count} marker(s)"
            ),
            current=0,
            total=len(clusters),
            warning=marker_warning,
        )

        if matching.get("download_images"):
            image_count = sum(
                bool(marker.get("image_url"))
                for marker in city_payload["markers"]
            )

            def city_image_progress(
                stage: str,
                current: int,
                total: int,
                message: str,
            ) -> None:
                ratio = current / total if total else 1
                progress.update(
                    stage=stage,
                    percent=65 + 18 * ratio,
                    message=message,
                    current=current,
                    total=total,
                    warning=(
                        (
                            f"Large city picture workload: {total} SAC "
                            "pictures will be read from cache or downloaded."
                        )
                        if total >= int(
                            matching["large_reference_warning"]
                        ) else None
                    ),
                )

            progress.update(
                stage="sac-city-images",
                percent=65,
                message=f"Preparing {image_count} SAC city picture(s)",
                current=0,
                total=image_count,
            )
            image_summary = cache_city_images(
                city_payload["markers"],
                _resolve(config_root, paths["reference_images"]),
                throttle=throttle,
                progress=city_image_progress,
            )
            progress.update(
                stage="sac-city-images",
                percent=83,
                message=(
                    f"Prepared {image_summary['cached']} SAC picture(s); "
                    f"{image_summary['failed']} failed"
                ),
                current=image_summary["available"],
                total=image_summary["available"],
            )

        def sac_progress(
            stage: str,
            current: int,
            total: int,
            message: str,
        ) -> None:
            ratio = current / total if total else 1
            if stage == "sac-images":
                percent = 83 + 9 * ratio
                warning = (
                    (
                        f"Large reference workload: {total} nearby SAC "
                        "images may be downloaded or read from cache."
                    )
                    if total >= int(
                        matching["large_reference_warning"]
                    ) else None
                )
            else:
                percent = 65 + 18 * ratio
                warning = None
            progress.update(
                stage=stage,
                percent=percent,
                message=message,
                current=current,
                total=total,
                warning=warning,
            )

        evidence = compare_clusters(
            clusters,
            city_payload,
            artist_mapping_path=_resolve(config_root, paths["artists"]),
            reference_cache=_resolve(
                config_root, paths["reference_images"]
            ),
            candidate_radius_m=float(matching["candidate_radius_m"]),
            visual_enabled=bool(matching.get("visual_enabled")),
            profile=str(matching["profile"]),
            throttle=throttle,
            progress=sac_progress,
        )
        progress.update(
            stage="sac-matching",
            percent=92,
            message=f"Compared {len(clusters)} cluster(s)",
            current=len(clusters),
            total=len(clusters),
        )
    else:
        progress.update(
            stage="reporting",
            percent=85,
            message="Street Art Cities matching is disabled",
        )
    progress.update(
        stage="reporting",
        percent=96,
        message="Writing JSON and Markdown reports",
    )
    write_cluster_report(
        clusters,
        output_directory / "report.json",
        output_directory / "report.md",
        city=city,
        sac_evidence=evidence,
    )
    progress.update(
        stage="complete",
        percent=100,
        message=(
            f"Report complete: {len(clusters)} cluster(s), "
            f"{preview.selected} photo(s)"
        ),
        current=len(clusters),
        total=len(clusters),
    )
    return {
        "scanned": preview.scanned,
        "selected": preview.selected,
        "clusters": len(clusters),
        "output_directory": str(output_directory.resolve()),
    }
