"""Mission API checks against a fake rover; never moves real wheels."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dashboard import make_handler


class FakeRover(BaseHTTPRequestHandler):
    stops = 0

    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path != '/stop':
            self.send_error(404)
            return
        type(self).stops += 1
        self.send_response(200)
        self.send_header('Content-Length', '7')
        self.end_headers()
        self.wfile.write(b'stopped')


class FakeRoutes:
    def get(self, run_id):
        if run_id == 'c3c666243fd2':
            return {'localization_destination': {'x_m': 1.0, 'y_m': 0.0}}
        return None


def post(base, endpoint, body):
    request = Request(base + endpoint, data=json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(request) as response:
        return json.load(response)


class MissionApiTest(unittest.TestCase):
    def test_start_requires_live_ros_and_cancel_sends_stop(self):
        with TemporaryDirectory() as directory:
            mission_dir = Path(directory)
            rover = ThreadingHTTPServer(('127.0.0.1', 0), FakeRover)
            service = SimpleNamespace(rover=f'http://127.0.0.1:{rover.server_port}',
                                      mission_dir=mission_dir, routes=FakeRoutes(),
                                      control_lock=threading.Lock(), drive_quiet_until=0)
            dashboard = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(service))
            for server in (rover, dashboard):
                threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{dashboard.server_port}'
            try:
                with self.assertRaises(HTTPError) as raised:
                    post(base, '/api/mission/start', {'id': 'c3c666243fd2'})
                self.assertEqual(raised.exception.code, 400)
                (mission_dir/'status.json').write_text(json.dumps(
                    {'at': time.time(), 'state': 'idle', 'map_id': 'c3c666243fd2'}))
                self.assertTrue(post(base, '/api/mission/start',
                                     {'id': 'c3c666243fd2', 'round_trip': True})['queued'])
                command = json.loads((mission_dir/'command.json').read_text())
                self.assertEqual(command['action'], 'start')
                self.assertTrue(command['round_trip'])
                (mission_dir/'status.json').write_text(json.dumps(
                    {'at': time.time(), 'state': 'active', 'map_id': 'c3c666243fd2'}))
                with self.assertRaises(HTTPError):
                    post(base, '/api/drive', {'direction': 'forward'})
                self.assertTrue(post(base, '/api/mission/cancel', {})['stop_sent'])
                self.assertGreater(FakeRover.stops, 0)
                self.assertEqual(json.loads((mission_dir/'command.json').read_text())['action'], 'cancel')
            finally:
                for server in (dashboard, rover):
                    server.shutdown()
                    server.server_close()


if __name__ == '__main__':
    unittest.main()
