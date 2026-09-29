from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from webapp.rover_control import normalize_rover_url, rover_request
from webapp.app import RoverRequest, rover_connect


class RoverControlTests(unittest.TestCase):
    @patch("webapp.app.rover_request")
    @patch("webapp.app.gamepad_bridge.stop")
    @patch("webapp.app.autonomy.stop")
    def test_connect_skips_legacy_mode_for_signed_wheel_esp(self, _autonomy: MagicMock,
                                                           _gamepad: MagicMock, send: MagicMock) -> None:
        send.side_effect = [{"signed_wheels": True}, {"motion": "Stopped", "speed": 160}]
        result = rover_connect(RoverRequest(base_url="http://192.168.0.99"))
        self.assertEqual(result["motion"], "Stopped")
        self.assertEqual([call.args[1] for call in send.call_args_list],
                         ["/api/capabilities", "/api/status"])

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
