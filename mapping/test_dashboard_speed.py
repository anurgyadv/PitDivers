"""Speed and drive proxy checks without issuing a real rover motor command."""

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dashboard import make_handler


class FakeRover(BaseHTTPRequestHandler):
    speed = 160

    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == '/api/status':
            body = json.dumps({'motion': 'stopped', 'speed': type(self).speed}).encode()
        elif self.path.startswith('/speed?value='):
            type(self).speed = int(self.path.split('=')[1])
            body = str(type(self).speed).encode()
        elif self.path == '/stop':
            time.sleep(.45)  # A slow but successful ESP response must not be called lost.
            body = b'stopped'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DashboardSpeedTest(unittest.TestCase):
    def test_proxy_reads_and_sets_speed_without_drive(self):
        rover = ThreadingHTTPServer(('127.0.0.1', 0), FakeRover)
        mission = TemporaryDirectory()
        service = SimpleNamespace(rover=f'http://127.0.0.1:{rover.server_port}',
                                  control_lock=threading.Lock(), mission_dir=mission.name)
        dashboard = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(service))
        threads = [threading.Thread(target=server.serve_forever, daemon=True)
                   for server in (rover, dashboard)]
        for thread in threads:
            thread.start()
        base = f'http://127.0.0.1:{dashboard.server_port}'
        try:
            with urlopen(base + '/api/drive/status') as response:
                self.assertEqual(json.load(response)['speed'], 160)
            request = Request(base + '/api/speed', data=b'{"value":180}',
                              headers={'Content-Type': 'application/json'}, method='POST')
            with urlopen(request) as response:
                self.assertEqual(json.load(response)['speed'], 180)
            with urlopen(base + '/api/drive/status') as response:
                self.assertEqual(json.load(response)['speed'], 180)
            request = Request(base + '/api/speed', data=b'{"value":256}',
                              headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(HTTPError) as raised:
                urlopen(request)
            self.assertEqual(raised.exception.code, 400)
            self.assertEqual(FakeRover.speed, 180)
            request = Request(base + '/api/drive', data=b'{"direction":"stop"}',
                              headers={'Content-Type': 'application/json'}, method='POST')
            with urlopen(request) as response:
                self.assertTrue(json.load(response)['ok'])
        finally:
            for server in (dashboard, rover):
                server.shutdown()
                server.server_close()
            mission.cleanup()


if __name__ == '__main__':
    unittest.main()
