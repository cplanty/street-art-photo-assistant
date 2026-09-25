import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path

from street_art_photo_assistant.clustering import (
    SelectionCriteria,
    cluster_photos,
    select_photos,
)
from street_art_photo_assistant.models import PhotoRecord


def photo(
    name,
    *,
    tags=(),
    latitude=48.0,
    longitude=2.0,
    captured_at=datetime(2026, 1, 2, 12, 0),
):
    return PhotoRecord(
        path=Path(name),
        source="Camera",
        captured_at=captured_at,
        latitude=latitude,
        longitude=longitude,
        tags=tuple(tags),
    )


class SelectionTests(unittest.TestCase):
    def test_combines_dates_tags_and_missing_gps(self):
        photos = [
            photo("keep.jpg", tags=["Artist"]),
            photo("wrong-tag.jpg", tags=["Other"]),
            photo(
                "wrong-date.jpg",
                tags=["Artist"],
                captured_at=datetime(2025, 12, 31, 12, 0),
            ),
            photo("missing.jpg", tags=["Artist"], latitude=None, longitude=None),
        ]
        selected, preview = select_photos(
            photos,
            SelectionCriteria(
                start=date(2026, 1, 1),
                include_tags=("artist",),
                missing_gps="exclude",
            ),
        )

        self.assertEqual(["keep.jpg"], [p.path.name for p in selected])
        self.assertEqual(4, preview.scanned)
        self.assertEqual(1, preview.selected)

    def test_date_times_form_one_range_across_midnight(self):
        photos = [
            photo("before.jpg", captured_at=datetime(2026, 1, 1, 11, 59)),
            photo("start.jpg", captured_at=datetime(2026, 1, 1, 12, 0)),
            photo("overnight.jpg", captured_at=datetime(2026, 1, 2, 2, 0)),
            photo("end.jpg", captured_at=datetime(2026, 1, 2, 12, 0)),
            photo("after.jpg", captured_at=datetime(2026, 1, 2, 12, 1)),
        ]

        selected, _preview = select_photos(
            photos,
            SelectionCriteria(
                start=date(2026, 1, 1),
                start_time=time(12, 0),
                end=date(2026, 1, 2),
                end_time=time(12, 0),
            ),
        )

        self.assertEqual(
            ["start.jpg", "overnight.jpg", "end.jpg"],
            [item.path.name for item in selected],
        )

    def test_times_without_dates_remain_a_daily_window(self):
        selected, _preview = select_photos(
            [
                photo("morning.jpg", captured_at=datetime(2026, 1, 1, 9, 0)),
                photo("afternoon.jpg", captured_at=datetime(2026, 1, 2, 14, 0)),
            ],
            SelectionCriteria(start_time=time(8, 0), end_time=time(12, 0)),
        )

        self.assertEqual(["morning.jpg"], [item.path.name for item in selected])


class ClusteringTests(unittest.TestCase):
    def test_nearby_same_tag_groups_and_far_photo_splits(self):
        clusters = cluster_photos(
            [
                photo("one.jpg", tags=["Artist"]),
                photo(
                    "two.jpg",
                    tags=["Artist"],
                    latitude=48.0001,
                    longitude=2.0,
                ),
                photo(
                    "far.jpg",
                    tags=["Artist"],
                    latitude=48.01,
                    longitude=2.0,
                ),
            ],
            radius_m=30,
        )
        self.assertEqual([1, 2], sorted(len(c.photos) for c in clusters))

    def test_unlocated_photos_do_not_collapse(self):
        clusters = cluster_photos(
            [
                photo("one.jpg", tags=["Artist"], latitude=None, longitude=None),
                photo("two.jpg", tags=["Artist"], latitude=None, longitude=None),
            ],
            radius_m=30,
        )
        self.assertEqual(2, len(clusters))

    def test_only_feature_internal_tags_are_retained(self):
        clusters = cluster_photos(
            [
                photo("unknown.jpg", tags=[]),
                photo("wall.jpg", tags=["_Wall_"]),
                photo("generic.jpg", tags=["StreetArt"]),
            ],
            radius_m=30,
            generic_tags=["StreetArt"],
        )
        self.assertEqual(["_Wall_", "_unknown"], sorted({c.tag for c in clusters}))

    def test_legacy_wall_tag_is_canonicalized(self):
        clusters = cluster_photos(
            [photo("wall.jpg", tags=["_wall"])],
            radius_m=50,
            wall_tag="_Wall_",
        )

        self.assertEqual(["_Wall_"], [cluster.tag for cluster in clusters])

    def test_multi_identity_photo_is_context_for_nearby_primary(self):
        clusters = cluster_photos(
            [
                photo("primary.jpg", tags=["Artist"]),
                photo("wide.jpg", tags=["Artist", "Second"]),
            ],
            radius_m=30,
        )
        artist = next(cluster for cluster in clusters if cluster.tag == "Artist")
        self.assertEqual(["wide.jpg"], [p.path.name for p in artist.context_photos])


if __name__ == "__main__":
    unittest.main()
