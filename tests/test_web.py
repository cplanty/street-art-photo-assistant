import unittest
from pathlib import Path

from street_art_photo_assistant.config import DEFAULT_CONFIG
from street_art_photo_assistant.web import create_app


class WebTests(unittest.TestCase):
    def test_health_and_empty_index(self):
        app = create_app(DEFAULT_CONFIG, Path("config.local.json"))
        client = app.test_client()

        self.assertEqual({"status": "ok"}, client.get("/health").get_json())
        response = client.get("/")
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Street Art Photo Assistant", response.data)


if __name__ == "__main__":
    unittest.main()

