from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from webapp.rover_control import normalize_rover_url, rover_request


class RoverControlTests(unittest.TestCase):
    def test_normalizes_controller_to_origin(self) -> None:
        self.assertEqual(
            normalize_rover_url(" http://192.168.0.70/some/path "),
            "http://192.168.0.70",
        )

    def test_rejects_invalid_or_credentialed_urls(self) -> None:
        for value in ("192.168.0.70", "ftp://192.168.0.70", "http://user:pass@rover"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_rover_url(value)

    @patch("webapp.rover_control.urlopen")
    def test_builds_command_request_and_reads_text(self, mocked_urlopen: MagicMock) -> None:
        response = MagicMock()
        response.read.return_value = b"forward"
        response.headers.get_content_type.return_value = "text/plain"
        mocked_urlopen.return_value.__enter__.return_value = response

        payload = rover_request(
            "http://rover.local", "/forward", params={"value": 180},
            headers={"X-API-Key": "test-key"},
        )

        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://rover.local/forward?value=180")
        self.assertEqual(request.get_header("X-api-key"), "test-key")
        self.assertEqual(payload, {"ok": True, "response": "forward"})


if __name__ == "__main__":
    unittest.main()
