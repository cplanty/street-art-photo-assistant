import unittest
from pathlib import Path
from unittest.mock import patch

from street_art_photo_assistant.matching import split_cluster
from street_art_photo_assistant.models import PhotoCluster, PhotoRecord


class MatchingTests(unittest.TestCase):
    def test_dissimilar_evidence_splits_cluster(self):
        photos = [
            PhotoRecord(Path("one.jpg"), "Camera", None, 48.0, 2.0),
            PhotoRecord(Path("two.jpg"), "Camera", None, 48.0, 2.0),
        ]
        cluster = PhotoCluster(
            id="cluster",
            tag="Artist",
            photos=photos,
            latitude=48.0,
            longitude=2.0,
        )

        with patch(
            "street_art_photo_assistant.matching.image_similarity",
            return_value=0.01,
        ):
            results = split_cluster(cluster, threshold=0.08)

        self.assertEqual(2, len(results))
        self.assertEqual([1, 2], [result.visual_group for result in results])


if __name__ == "__main__":
    unittest.main()

