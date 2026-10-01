import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from street_art_photo_assistant.matching import image_similarity, split_cluster
from street_art_photo_assistant.models import PhotoCluster, PhotoRecord


class MatchingTests(unittest.TestCase):
    @unittest.skipUnless(
        importlib.util.find_spec("cv2"),
        "OpenCV visual dependency is not installed",
    )
    def test_similarity_normalizes_original_and_provider_derivative_scale(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original_path = root / "original.jpg"
            derivative_path = root / "derivative.jpg"
            original = Image.new("RGB", (1600, 1200), "white")
            draw = ImageDraw.Draw(original)
            for offset in range(0, 1200, 80):
                draw.line((0, offset, 1599, 1199 - offset), fill="black", width=8)
                draw.ellipse(
                    (offset, offset // 2, offset + 120, offset // 2 + 90),
                    outline="red",
                    width=6,
                )
            original.save(original_path, quality=95)
            original.resize((400, 300)).save(derivative_path, quality=85)

            similarity = image_similarity(original_path, derivative_path)

        self.assertIsNotNone(similarity)
        self.assertGreater(similarity, 0.5)

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
