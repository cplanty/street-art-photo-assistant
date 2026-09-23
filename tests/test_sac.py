import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from street_art_photo_assistant.models import PhotoCluster
from street_art_photo_assistant.sac import (
    USER_AGENT,
    RequestThrottle,
    cache_city_images,
    cache_reference_image,
    cached_cities,
    compare_clusters,
    nearby_candidates,
    refresh_city,
)


class FakeResponse:
    def __init__(self, payload=None, *, content=b"", content_type="image/jpeg"):
        self.payload = payload
        self.content = content
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]


class SACTests(unittest.TestCase):
    def marker_item(self):
        return {
            "id": "marker-1",
            "type": "artwork",
            "status": "active",
            "href": "/cities/test/markers/marker-1",
            "title": "Synthetic marker",
            "artistsString": "Public Artist",
            "artists": [{"slug": "public-artist"}],
            "location": {
                "lat": 48.0,
                "lng": 2.0,
                "address": "Example street",
            },
            "images": [{"url": "https://images.example.test/reference.jpg"}],
        }

    def test_refresh_normalizes_and_caches_all_artwork_statuses(self):
        removed = {**self.marker_item(), "id": "marker-2", "status": "removed"}
        session = Mock()
        session.get.return_value = FakeResponse({
            "items": [
                self.marker_item(),
                removed,
                {"id": "place-1", "type": "place"},
            ]
        })
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)

            payload = refresh_city("test-city", cache, session=session)

            saved = json.loads(
                (cache / "test-city.json").read_text(encoding="utf-8")
            )
            cities = cached_cities(cache)
        self.assertEqual(["active", "removed"], [
            marker["status"] for marker in payload["markers"]
        ])
        self.assertEqual(payload, saved)
        self.assertEqual(["test-city"], cities)
        session.get.assert_called_once()
        self.assertEqual(
            USER_AGENT,
            session.get.call_args.kwargs["headers"]["User-Agent"],
        )

    def test_nearby_candidates_rank_same_artist_first(self):
        cluster = PhotoCluster(
            id="cluster",
            tag="Artist",
            latitude=48.0,
            longitude=2.0,
        )
        markers = [
            {
                "marker_id": "other",
                "latitude": 48.00001,
                "longitude": 2.0,
                "artist_slug": "other",
            },
            {
                "marker_id": "same",
                "latitude": 48.00002,
                "longitude": 2.0,
                "artist_slug": "artist",
            },
        ]

        candidates = nearby_candidates(
            cluster, markers, radius_m=100, artist_slug="artist"
        )

        self.assertEqual(["same", "other"], [
            candidate["marker_id"] for candidate in candidates
        ])
        self.assertTrue(candidates[0]["tag_match"])

    def test_comparison_without_visual_matching_makes_no_image_request(self):
        cluster = PhotoCluster(
            id="cluster",
            tag="Artist",
            latitude=48.0,
            longitude=2.0,
        )
        city = {"city": "test-city", "markers": [{
            "marker_id": "same",
            "latitude": 48.0,
            "longitude": 2.0,
            "artist_slug": "artist",
            "image_url": "https://images.example.test/reference.jpg",
            "status": "active",
        }]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artists = root / "artists.csv"
            artists.write_text(
                "tag;streetartcities_slug;instagram;status\n"
                "Artist;artist;artist;confirmed\n",
                encoding="utf-8",
            )
            session = Mock()

            result = compare_clusters(
                [cluster],
                city,
                artist_mapping_path=artists,
                reference_cache=root / "refs",
                candidate_radius_m=100,
                visual_enabled=False,
                profile="balanced",
                session=session,
            )

        self.assertEqual("review", result["cluster"]["status"])
        session.get.assert_not_called()

    def test_cached_city_picture_is_kept_without_visual_matching(self):
        cluster = PhotoCluster(
            id="cluster",
            tag="Artist",
            latitude=48.0,
            longitude=2.0,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cached = root / "marker.jpg"
            cached.write_bytes(b"already verified cache")
            artists = root / "artists.csv"
            artists.write_text(
                "tag;streetartcities_slug;instagram;status\n"
                "Artist;artist;artist;confirmed\n",
                encoding="utf-8",
            )
            result = compare_clusters(
                [cluster],
                {"city": "test-city", "markers": [{
                    "marker_id": "marker",
                    "latitude": 48.0,
                    "longitude": 2.0,
                    "artist_slug": "artist",
                    "cached_image": str(cached),
                }]},
                artist_mapping_path=artists,
                reference_cache=root,
                candidate_radius_m=100,
                visual_enabled=False,
                profile="balanced",
            )

        self.assertEqual(
            str(cached),
            result["cluster"]["candidates"][0]["cached_image"],
        )

    def test_reference_cache_rejects_invalid_image_content(self):
        session = Mock()
        session.get.return_value = FakeResponse(content=b"not an image")
        marker = {
            "marker_id": "marker-1",
            "image_url": "https://images.example.test/reference.jpg",
        }
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            with self.assertRaises(OSError):
                cache_reference_image(marker, cache, session=session)
            self.assertFalse((cache / "marker-1.jpg").exists())
            self.assertFalse((cache / "marker-1.jpg.tmp").exists())

    def test_reference_cache_accepts_a_bounded_https_image(self):
        image_bytes = BytesIO()
        Image.new("RGB", (4, 4), "blue").save(image_bytes, format="JPEG")
        session = Mock()
        session.get.return_value = FakeResponse(content=image_bytes.getvalue())
        marker = {
            "marker_id": "../marker 1",
            "image_url": "https://images.example.test/reference.jpg",
        }
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)

            cached = cache_reference_image(
                marker,
                cache,
                maximum_bytes=len(image_bytes.getvalue()),
                session=session,
            )

            self.assertEqual(cache / "marker-1.jpg", cached)
            self.assertTrue(cached.is_file())

    def test_city_picture_download_caches_images_and_reports_progress(self):
        image_bytes = BytesIO()
        Image.new("RGB", (4, 4), "green").save(image_bytes, format="JPEG")
        session = Mock()
        session.get.return_value = FakeResponse(content=image_bytes.getvalue())
        markers = [
            {
                "marker_id": "marker-1",
                "image_url": "https://images.example.test/one.jpg",
            },
            {
                "marker_id": "marker-2",
                "image_url": None,
            },
        ]
        progress = []
        with tempfile.TemporaryDirectory() as temporary:
            summary = cache_city_images(
                markers,
                Path(temporary),
                session=session,
                progress=lambda *event: progress.append(event),
            )

        self.assertEqual(
            {"available": 1, "cached": 1, "failed": 0},
            summary,
        )
        self.assertTrue(markers[0]["cached_image"].endswith("marker-1.jpg"))
        self.assertEqual("sac-city-images", progress[0][0])
        self.assertEqual(USER_AGENT, session.get.call_args.kwargs[
            "headers"
        ]["User-Agent"])

    def test_visual_reference_failure_is_reported_without_aborting(self):
        cluster = PhotoCluster(
            id="cluster",
            tag="Artist",
            latitude=48.0,
            longitude=2.0,
        )
        city = {"city": "test-city", "markers": [{
            "marker_id": "same",
            "latitude": 48.0,
            "longitude": 2.0,
            "artist_slug": "artist",
            "image_url": "https://images.example.test/reference.jpg",
            "status": "active",
        }]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artists = root / "artists.csv"
            artists.write_text(
                "tag;streetartcities_slug;instagram;status\n"
                "Artist;artist;artist;confirmed\n",
                encoding="utf-8",
            )
            session = Mock()
            session.get.return_value = FakeResponse(
                content=b"text", content_type="text/plain"
            )
            cluster.photos.append(Mock(path=root / "photo.jpg"))
            progress = []

            result = compare_clusters(
                [cluster],
                city,
                artist_mapping_path=artists,
                reference_cache=root / "refs",
                candidate_radius_m=100,
                visual_enabled=True,
                profile="balanced",
                session=session,
                progress=lambda *event: progress.append(event),
            )

        candidate = result["cluster"]["candidates"][0]
        self.assertIn("not an image", candidate["visual_error"])
        self.assertIsNone(candidate["visual_similarity"])
        self.assertEqual("sac-matching", progress[0][0])
        self.assertEqual("sac-images", progress[-1][0])

    def test_request_throttle_enforces_minimum_interval(self):
        throttle = RequestThrottle(0.5)
        with (
            patch(
                "street_art_photo_assistant.sac.time.monotonic",
                side_effect=[10.0, 10.1, 10.5],
            ),
            patch(
                "street_art_photo_assistant.sac.time.sleep"
            ) as sleep,
        ):
            throttle.wait()
            throttle.wait()

        sleep.assert_called_once()
        self.assertAlmostEqual(0.4, sleep.call_args.args[0])

    def test_disabled_matching_workflow_never_calls_network(self):
        from copy import deepcopy
        from shutil import copy2

        from street_art_photo_assistant.config import DEFAULT_CONFIG
        from street_art_photo_assistant.workflow import run_offline_clustering

        fixtures = Path(__file__).parent / "fixtures"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            photos = root / "photos"
            photos.mkdir()
            copy2(fixtures / "located.jpg", photos / "photo.jpg")
            config = deepcopy(DEFAULT_CONFIG)
            config["sources"] = [{
                "name": "Camera",
                "path": str(photos),
                "enabled": True,
            }]
            with patch(
                "requests.sessions.Session.get",
                side_effect=AssertionError("network request"),
            ):
                result = run_offline_clustering(
                    config,
                    config_root=root,
                    output_directory=root / "output",
                )

        self.assertEqual(1, result["clusters"])


if __name__ == "__main__":
    unittest.main()
