"""Optional local OpenCV matching used to split ambiguous clusters."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .models import PhotoCluster, PhotoRecord


def image_similarity(left: Path, right: Path) -> float | None:
    """Return an ORB match ratio, or None when an image has no usable features."""

    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            'Visual matching requires: pip install -e ".[visual]"'
        ) from exc

    left_image = cv2.imread(str(left), cv2.IMREAD_GRAYSCALE)
    right_image = cv2.imread(str(right), cv2.IMREAD_GRAYSCALE)
    if left_image is None or right_image is None:
        raise ValueError(f"Could not decode images for matching: {left}, {right}")
    target_dimension = min(
        1024,
        max(left_image.shape),
        max(right_image.shape),
    )

    def normalized(image):
        scale = target_dimension / max(image.shape)
        if scale == 1:
            return image
        size = (
            max(1, round(image.shape[1] * scale)),
            max(1, round(image.shape[0] * scale)),
        )
        return cv2.resize(image, size, interpolation=cv2.INTER_AREA)

    left_image = normalized(left_image)
    right_image = normalized(right_image)
    detector = cv2.ORB_create(nfeatures=1200)
    left_keypoints, left_descriptors = detector.detectAndCompute(left_image, None)
    right_keypoints, right_descriptors = detector.detectAndCompute(
        right_image, None
    )
    if (
        left_descriptors is None
        or right_descriptors is None
        or not left_keypoints
        or not right_keypoints
    ):
        return None
    matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(
        left_descriptors, right_descriptors, k=2
    )
    good = [
        first
        for pair in matches
        if len(pair) == 2
        for first, second in [pair]
        if first.distance < 0.75 * second.distance
    ]
    return len(good) / max(1, min(len(left_keypoints), len(right_keypoints)))


def split_cluster(
    cluster: PhotoCluster,
    *,
    threshold: float = 0.08,
) -> list[PhotoCluster]:
    """Split a cluster when local matching provides dissimilar evidence."""

    if len(cluster.photos) < 2:
        return [cluster]
    groups: list[list[PhotoRecord]] = []
    for photo in cluster.photos:
        placed = False
        for group in groups:
            score = image_similarity(photo.path, group[0].path)
            if score is None or score >= threshold:
                group.append(photo)
                placed = True
                break
        if not placed:
            groups.append([photo])
    if len(groups) == 1:
        return [cluster]

    results = []
    for index, photos in enumerate(groups, start=1):
        latitude = (
            sum(photo.latitude for photo in photos if photo.latitude is not None)
            / len(photos)
            if all(photo.has_gps for photo in photos)
            else cluster.latitude
        )
        longitude = (
            sum(
                photo.longitude for photo in photos if photo.longitude is not None
            )
            / len(photos)
            if all(photo.has_gps for photo in photos)
            else cluster.longitude
        )
        results.append(
            replace(
                cluster,
                id=f"{cluster.id}-{index}",
                photos=photos,
                context_photos=list(cluster.context_photos),
                latitude=latitude,
                longitude=longitude,
                visual_group=index,
            )
        )
    return results


def visual_subcluster(
    clusters: list[PhotoCluster],
    *,
    threshold: float = 0.08,
) -> list[PhotoCluster]:
    """Apply local visual splitting to every cluster."""

    return [
        subgroup
        for cluster in clusters
        for subgroup in split_cluster(cluster, threshold=threshold)
    ]
