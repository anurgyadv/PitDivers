"""One supervised short out-and-back with a temporary B; restores the saved B."""

import json
import math
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

from routes import RouteStore

ROOT = Path(__file__).resolve().parent.parent
MAP_ID = 'c3c666243fd2'
DASH = 'http://127.0.0.1:8767'
ROVER = 'http://192.168.0.99'


def request(path, data=None):
    payload = None if data is None else json.dumps(data).encode()
    with urlopen(Request(DASH + path, data=payload,
                         headers={'Content-Type': 'application/json'}), timeout=3) as response:
        return json.load(response)


def main():
    store = RouteStore(ROOT / 'data/lidar-maps', ROOT / 'data/lidar-routes')
    route_file = store.routes_dir / f'{MAP_ID}.json'
    original = route_file.read_bytes()
    status = request('/api/mission/status')
    if (status.get('state') != 'idle' or status.get('pose_age_s', 99) > .6
            or status.get('scan_age_s', 99) > .6
            or status.get('front_m', 0) < .45 or status.get('rear_m', 0) < .45
            or math.dist(status.get('pose', [99, 99])[:2], [0, 0]) > .35):
        raise RuntimeError(f'Unsafe preflight: {status}')
    active = False
    try:
        route = store.set(MAP_ID, -.796, .11)
        print('Trial B:', route['localization_destination'], flush=True)
        print('Queued:', request('/api/mission/start',
                                 {'id': MAP_ID, 'round_trip': True}), flush=True)
        active = True
        started = time.monotonic()
        last_progress = started
        last_pose = status['pose'][:2]
        last_print = 0
        while time.monotonic() - started < 75:
            time.sleep(.3)
            status = request('/api/mission/status')
            now = time.monotonic()
            pose = status.get('pose') or []
            if len(pose) >= 2 and math.dist(pose[:2], last_pose) >= .06:
                last_progress, last_pose = now, pose[:2]
            if now - last_print > 1:
                print(round(now - started, 1), status.get('state'),
                      status.get('phase'), pose, status.get('reason'), flush=True)
                last_print = now
            if status['state'] in ('arrived', 'aborted', 'rejected', 'cancelled'):
                active = False
                print('FINAL', json.dumps(status), flush=True)
                return 0 if status['state'] == 'arrived' else 2
            if status['state'] == 'offline' or (now - last_progress > 5):
                raise RuntimeError('Localization process offline or no pose progress for 5s')
        raise RuntimeError('Trial exceeded 75s')
    finally:
        if active:
            try:
                print('Cancel:', request('/api/mission/cancel', {}), flush=True)
            except Exception as exc:
                print('Cancel error:', exc, file=sys.stderr, flush=True)
        try:
            urlopen(ROVER + '/stop', timeout=2).read()
        except Exception as exc:
            print('Stop error:', exc, file=sys.stderr, flush=True)
        route_file.write_bytes(original)
        print('Original B restored; stop sent.', flush=True)


if __name__ == '__main__':
    sys.exit(main())
