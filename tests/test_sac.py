import json
import tempfile
import unittest
from base64 import urlsafe_b64decode
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import requests
from PIL import Image

from street_art_photo_assistant.models import PhotoCluster
from street_art_photo_assistant.sac import (
    SACAuthorizationError,
    USER_AGENT,
    RequestThrottle,
    cache_city_images,
    cache_reference_image,
    cached_cities,
    compare_clusters,
    create_pkce_pair,
    exchange_pkce_code,
    fetch_collections,
    fetch_my_edits,
    load_artist_mapping,
    nearby_candidates,
    oauth_authorization_url,
    refresh_city,
    refresh_city_api,
    refresh_city_artists,
    request_media_upload,
    submit_marker_creation,
    upload_media_file,
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

    def test_pkce_authorization_and_authenticated_first_request(self):
        verifier, challenge = create_pkce_pair()
        padded = challenge + "=" * (-len(challenge) % 4)
        self.assertGreaterEqual(len(verifier), 43)
        self.assertLessEqual(len(verifier), 128)
        self.assertEqual(
            sha256(verifier.encode("ascii")).digest(),
            urlsafe_b64decode(padded),
        )
        url = oauth_authorization_url(
            client_id="sac_client_test",
            redirect_uri="http://127.0.0.1:8787/login",
            scope="collections:read",
            state="state-value",
            code_challenge=challenge,
        )
        query = parse_qs(urlparse(url).query)
        self.assertEqual(["code"], query["response_type"])
        self.assertEqual(["S256"], query["code_challenge_method"])
        self.assertEqual(["collections:read"], query["scope"])

        session = Mock()
        session.post.return_value = FakeResponse({
            "access_token": "test-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "collections:read",
        })
        token = exchange_pkce_code(
            client_id="sac_client_test",
            redirect_uri="http://127.0.0.1:8787/login",
            code="one-use-code",
            code_verifier=verifier,
            session=session,
        )
        self.assertEqual("test-access-token", token["access_token"])
        token_request = session.post.call_args.kwargs
        self.assertEqual(verifier, token_request["json"]["code_verifier"])
        self.assertNotIn("client_secret", token_request["json"])

        session.get.return_value = FakeResponse([{"id": "collection-1"}])
        collections = fetch_collections(
            token["access_token"], session=session
        )
        self.assertEqual([{"id": "collection-1"}], collections)
        self.assertEqual(
            "Bearer test-access-token",
            session.get.call_args.kwargs["headers"]["Authorization"],
        )

    def test_uploads_media_and_submits_marker_creation(self):
        session = Mock()
        session.get.return_value = FakeResponse({
            "key": "media/test/orig.jpg",
            "url": "https://uploads.example.test/signed",
            "publicUrl": (
                "https://streetartcities.com/media/test/orig.jpg"
            ),
        })
        upload = request_media_upload(
            "test-access-token",
            filename="art.jpg",
            content_type="image/jpeg",
            session=session,
        )
        self.assertEqual(
            "https://streetartcities.com/media/test/orig.jpg",
            upload["publicUrl"],
        )
        self.assertEqual(
            "Bearer " + "test-access-token",
            session.get.call_args.kwargs["headers"]["Authorization"],
        )

        session.put.return_value = FakeResponse()
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "art.jpg"
            image.write_bytes(b"synthetic-jpeg")
            upload_media_file(
                image,
                upload["url"],
                content_type="image/jpeg",
                session=session,
            )
        self.assertEqual(
            "image/jpeg",
            session.put.call_args.kwargs["headers"]["Content-Type"],
        )

        session.post.return_value = FakeResponse({"edit": {
            "id": "edit-1",
            "status": "submitted",
            "reviewUrl": (
                "https://streetartcities.com/community/review-queue/edit-1"
            ),
        }})
        edit = submit_marker_creation(
            "test-access-token",
            {
                "lat": 48.0,
                "lng": 2.0,
                "city": "test-city",
                "type": "artwork",
                "images": [{"url": upload["publicUrl"]}],
            },
            edit_comment="Synthetic test",
            session=session,
        )
        self.assertEqual("edit-1", edit["id"])
        body = session.post.call_args.kwargs["json"]
        self.assertNotIn("entityId", body)
        self.assertEqual("marker", body["entityType"])
        self.assertEqual("test-city", body["actions"]["city"])
        self.assertEqual(
            "Bearer " + "test-access-token",
            session.post.call_args.kwargs["headers"]["Authorization"],
        )

    def test_local_artist_overlay_adds_without_overriding_main(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            main = root / "artists.csv"
            local = root / "artists.local.csv"
            main.write_text(
                "tag;streetartcities_slug\n"
                "Shared;public-slug\n",
                encoding="utf-8",
            )
            local.write_text(
                "tag;streetartcities_slug\n"
                "Shared;local-slug\n"
                "Local Artist;local-artist\n",
                encoding="utf-8",
            )

            mapping = load_artist_mapping(main, (local,))

        self.assertEqual("public-slug", mapping["shared"])
        self.assertEqual("local-artist", mapping["local artist"])

    def test_marker_creation_reports_rejected_oauth_token(self):
        response = Mock(status_code=401)
        response.raise_for_status.side_effect = requests.HTTPError(
            "401 Client Error: Unauthorized",
            response=response,
        )
        session = Mock()
        session.post.return_value = response

        with self.assertRaisesRegex(
            SACAuthorizationError,
            "rejected authorization",
        ):
            submit_marker_creation(
                "rejected-token",
                {"city": "test-city"},
                session=session,
            )

    def test_fetches_owned_edits_by_id(self):
        session = Mock()
        session.get.return_value = FakeResponse({
            "edits": [{
                "id": "edit-1",
                "status": "submitted",
                "reviewUrl": (
                    "https://streetartcities.com/community/review-queue/edit-1"
                ),
            }],
        })

        edits = fetch_my_edits(
            "test-access-token",
            edit_ids=["edit-1"],
            session=session,
        )

        self.assertEqual("submitted", edits[0]["status"])
        self.assertEqual(
            {"ids": "edit-1"},
            session.get.call_args.kwargs["params"],
        )
        self.assertEqual(
            "Bearer " + "test-access-token",
            session.get.call_args.kwargs["headers"]["Authorization"],
        )

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

    def test_authenticated_marker_refresh_paginates_and_keeps_all_statuses(self):
        first = {
            **self.marker_item(),
            "siteId": "test-city",
            "images": [],
            "artists": [],
            "thumbnail": "https://images.example.test/thumb-1.jpg",
        }
        second = {
            **first,
            "id": "marker-2",
            "status": "removed",
            "thumbnail": "https://images.example.test/thumb-2.jpg",
        }
        session = Mock()
        session.get.side_effect = [
            FakeResponse({
                "items": [first],
                "page": 1,
                "perPage": 100,
                "total": 2,
            }),
            FakeResponse({
                "items": [second],
                "page": 2,
                "perPage": 100,
                "total": 2,
            }),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            payload = refresh_city_api(
                "test-city",
                Path(temporary),
                access_token="test-access-token",
                session=session,
            )

        self.assertEqual("oauth-markers-api", payload["source"])
        self.assertEqual(["active", "removed"], [
            marker["status"] for marker in payload["markers"]
        ])
        self.assertEqual(
            "https://images.example.test/thumb-1.jpg",
            payload["markers"][0]["image_url"],
        )
        self.assertEqual(2, session.get.call_count)
        for call in session.get.call_args_list:
            self.assertEqual("all", call.kwargs["params"]["status"])
            self.assertEqual("artwork", call.kwargs["params"]["type"])
            self.assertEqual(
                "Bearer test-access-token",
                call.kwargs["headers"]["Authorization"],
            )

    def test_flat_api_marker_shape_is_normalized(self):
        flat = {
            "id": "marker-9",
            "type": "artwork",
            "status": "active",
            "href": "/cities/test/markers/marker-9",
            "title": "Flat marker",
            "artistsString": "Public Artist",
            "artists": [{
                "id": "public-artist",
                "title": "Public Artist",
                "href": "https://streetartcities.com/artists/public-artist",
            }],
            "lat": 48.5,
            "lng": 2.5,
            "address": "Flat street",
            "city": {"id": "test-city", "title": "Test City"},
            "thumbnail": "https://images.example.test/flat.jpg",
        }
        session = Mock()
        session.get.return_value = FakeResponse({
            "items": [flat], "page": 1, "perPage": 100, "total": 1,
        })
        with tempfile.TemporaryDirectory() as temporary:
            payload = refresh_city_api(
                "test-city",
                Path(temporary),
                access_token="test-access-token",
                session=session,
            )

        marker = payload["markers"][0]
        self.assertEqual(48.5, marker["latitude"])
        self.assertEqual(2.5, marker["longitude"])
        self.assertEqual("Flat street", marker["address"])
        self.assertEqual("public-artist", marker["artist_slug"])
        self.assertEqual("Public Artist", marker["artist_name"])
        self.assertEqual("oldest", session.get.call_args.kwargs["params"]["sort"])

    def test_legacy_nested_marker_shape_is_still_normalized(self):
        session = Mock()
        session.get.return_value = FakeResponse({
            "items": [self.marker_item()]
        })
        with tempfile.TemporaryDirectory() as temporary:
            payload = refresh_city(
                "test-city", Path(temporary), session=session
            )

        marker = payload["markers"][0]
        self.assertEqual(48.0, marker["latitude"])
        self.assertEqual(2.0, marker["longitude"])
        self.assertEqual("public-artist", marker["artist_slug"])

    def test_artist_catalogue_paginates_and_caches(self):
        session = Mock()
        session.get.side_effect = [
            FakeResponse({
                "items": [{
                    "id": "public-artist",
                    "title": "Public Artist",
                    "alternativeTitles": ["Publik Artist"],
                    "artworksCount": 4,
                    "country": "France",
                    "href": "/artists/public-artist",
                    "updatedAt": "2026-02-01T08:30:00.000Z",
                }],
                "page": 1, "perPage": 100, "total": 2,
            }),
            FakeResponse({
                "items": [{
                    "id": "other-artist",
                    "title": "Other Artist",
                    "href": "/artists/other-artist",
                }],
                "page": 2, "perPage": 100, "total": 2,
            }),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            payload = refresh_city_artists(
                "test-city",
                cache,
                access_token="test-access-token",
                session=session,
            )
            saved = json.loads(
                (cache / "test-city.artists.json").read_text(encoding="utf-8")
            )
            self.assertEqual([], cached_cities(cache))

        self.assertEqual("oauth-artists-api", payload["source"])
        self.assertEqual(payload, saved)
        self.assertEqual(
            ["public-artist", "other-artist"],
            [artist["slug"] for artist in payload["artists"]],
        )
        self.assertEqual(
            ["Publik Artist"], payload["artists"][0]["alternative_names"]
        )
        self.assertEqual(
            "https://streetartcities.com/artists/public-artist",
            payload["artists"][0]["url"],
        )
        self.assertEqual(2, session.get.call_count)
        self.assertEqual(
            "Bearer test-access-token",
            session.get.call_args.kwargs["headers"]["Authorization"],
        )

    def test_incremental_refresh_merges_changed_markers_only(self):
        session = Mock()
        session.get.return_value = FakeResponse({
            "items": [{
                **self.marker_item(),
                "siteId": "test-city",
                "artists": [],
            }],
            "page": 1, "perPage": 100, "total": 1,
        })
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            first = refresh_city_api(
                "test-city",
                cache,
                access_token="test-access-token",
                session=session,
                incremental=True,
            )
            self.assertFalse(first["incremental"])
            self.assertNotIn(
                "updatedSince", session.get.call_args.kwargs["params"]
            )

            session.get.return_value = FakeResponse({
                "items": [
                    {
                        **self.marker_item(),
                        "title": "Renamed marker",
                        "siteId": "test-city",
                        "artists": [],
                    },
                    {
                        **self.marker_item(),
                        "id": "marker-2",
                        "status": "removed",
                        "siteId": "test-city",
                        "artists": [],
                    },
                ],
                "page": 1, "perPage": 100, "total": 2,
            })
            second = refresh_city_api(
                "test-city",
                cache,
                access_token="test-access-token",
                session=session,
                incremental=True,
            )
            saved = json.loads(
                (cache / "test-city.json").read_text(encoding="utf-8")
            )

        self.assertTrue(second["incremental"])
        self.assertEqual(
            first["synced_at"],
            session.get.call_args.kwargs["params"]["updatedSince"],
        )
        self.assertEqual(2, second["changed_since_last_sync"])
        self.assertEqual(
            ["marker-1", "marker-2"],
            [marker["marker_id"] for marker in second["markers"]],
        )
        self.assertEqual("Renamed marker", second["markers"][0]["title"])
        self.assertEqual("removed", second["markers"][1]["status"])
        self.assertEqual(second, saved)

    def test_incremental_refresh_ignores_a_public_snapshot_cache(self):
        session = Mock()
        session.get.return_value = FakeResponse({
            "items": [self.marker_item()]
        })
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            refresh_city("test-city", cache, session=session)

            session.get.return_value = FakeResponse({
                "items": [{
                    **self.marker_item(),
                    "siteId": "test-city",
                    "artists": [],
                }],
                "page": 1, "perPage": 100, "total": 1,
            })
            payload = refresh_city_api(
                "test-city",
                cache,
                access_token="test-access-token",
                session=session,
                incremental=True,
            )

        self.assertFalse(payload["incremental"])
        self.assertIsNone(payload["changed_since_last_sync"])
        self.assertNotIn(
            "updatedSince", session.get.call_args.kwargs["params"]
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

    def test_api_artist_display_name_can_prioritize_candidate(self):
        cluster = PhotoCluster(
            id="cluster",
            tag="Public Artist",
            latitude=48.0,
            longitude=2.0,
        )
        candidates = nearby_candidates(
            cluster,
            [{
                "marker_id": "other",
                "latitude": 48.00001,
                "longitude": 2.0,
                "artist": "Other Artist",
            }, {
                "marker_id": "same",
                "latitude": 48.00002,
                "longitude": 2.0,
                "artist": "Public Artist, Collaborator",
            }],
            radius_m=100,
            artist_tag=cluster.tag,
        )

        self.assertEqual(["same", "other"], [
            candidate["marker_id"] for candidate in candidates
        ])

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
