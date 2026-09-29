"""Local room-map dashboard. Run with `uv run --with numpy --with scipy python mapping/dashboard.py`."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen, Request
from urllib.parse import urlparse, parse_qs
from uuid import uuid4

from records import ScanStore, fetch_batch
from local_mapper import RoomMapper
from routes import RouteStore, valid_run_id
from autonav_io import read_status, write_command
from localization_view import make_localization_view
from atomic_snapshot import replace_with_retry
from drive_commands import manual_request

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).with_name('dashboard.html')
ROUTE_SCRIPT = Path(__file__).with_name('route.js')
COMPARE = Path(__file__).with_name('compare.html')


class MappingService:
    def __init__(self, rover, db, output):
        self.rover, self.db_path = rover.rstrip('/'), Path(db)
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.routes = RouteStore(self.output, self.output.parent / 'lidar-routes')
        self.mission_dir = self.output.parent / 'autonav'
        self.lock = threading.RLock()
        self.quit = threading.Event()
        self.store = ScanStore(self.db_path)
        self.store.db.executescript('''
            CREATE TABLE IF NOT EXISTS local_runs (id TEXT PRIMARY KEY, start_id INTEGER, created REAL, forward INTEGER, clockwise INTEGER);
            CREATE TABLE IF NOT EXISTS local_poses (run_id TEXT, scan_id INTEGER, x REAL, y REAL, yaw REAL, PRIMARY KEY(run_id, scan_id));
        ''')
        row = self.store.db.execute('SELECT id,start_id,created,forward,clockwise FROM local_runs ORDER BY created DESC LIMIT 1').fetchone()
        if row:
            self.run_id, self.start_id, self.created, forward, clockwise = row
        else:
            self.run_id, self.start_id, self.created, forward, clockwise = uuid4().hex[:12], 1, time.time(), 0, 1
            with self.store.db:
                self.store.db.execute('INSERT INTO local_runs VALUES(?,?,?,?,?)', (self.run_id, self.start_id, self.created, forward, clockwise))
        self.mapper = RoomMapper(forward, bool(clockwise))
        self.last_id = self.start_id - 1
        self.paused = False
        self.latest = None
        self.network = dict(connected=False, last_seen=None, error='Connecting to rover', sd=None)
        self.snapshot = self.mapper.snapshot()
        self.revision = 0
        self.control_lock = threading.Lock()
        self.drive_quiet_until = 0.0

    def start(self):
        for target in (self.collect, self.process):
            threading.Thread(target=target, daemon=True).start()

    def ros_session_active(self):
        if read_status(self.mission_dir)['state'] != 'offline':
            return True
        for name in ('mapping-session.json', 'localization-session.json'):
            try:
                stamp = json.loads((ROOT/'data/ros-map'/name).read_text())['at']
                if time.time() - stamp < (15 if name.startswith('localization') else 5):
                    return True
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return False

    def collect(self):
        # Separate SQLite connection: ingestion can continue while mapping catches up.
        store = ScanStore(self.db_path)
        last_status = 0
        last_live_fetch = 0
        try:
            while not self.quit.is_set():
                try:
                    # The ESP serves HTTP and microSD reads on one loop. Leave
                    # its SD log alone while manual wheel commands are active;
                    # the durable backlog is collected as soon as driving stops.
                    if time.monotonic() < self.drive_quiet_until and not self.ros_session_active():
                        self.quit.wait(.1)
                        continue
                    sync_paused = self.ros_session_active()
                    added = 0
                    if sync_paused:
                        if time.monotonic() - last_live_fetch >= .18:
                            last_live_fetch = time.monotonic()
                            with urlopen(self.rover + '/api/lidar/revolution', timeout=1) as response:
                                latest = json.load(response)
                            received_at = time.time()
                            with self.lock:
                                if self.latest is None or (latest['boot_id'], latest['seq']) != (self.latest['boot_id'], self.latest['seq']):
                                    self.network['scan_received_at'] = received_at
                                self.latest = latest
                                self.network.update(connected=True, last_seen=received_at, error=None)
                                self.network.setdefault('lidar', {}).update(
                                    running=latest.get('rpm', 0) > 0, rpm=latest.get('rpm'))
                            shared = ROOT/'data/ros-map/latest-rover.json'
                            temp = shared.with_suffix('.tmp')
                            temp.write_text(json.dumps({'received_at': received_at, 'record': latest}))
                            if not replace_with_retry(temp, shared):
                                raise OSError('Could not publish live LiDAR relay')
                        # Telemetry is already in each scan. Extra serial HTTP
                        # status calls used to pause this critical stream for
                        # up to two seconds every five seconds.
                        self.quit.wait(.04)
                        continue
                    if not sync_paused:
                        offset = store.offset()
                        batch = fetch_batch(self.rover, offset, timeout=2)
                        added, invalid = store.ingest(batch)
                        with self.lock:
                            self.network.update(connected=True, last_seen=time.time(), error=None)
                            self.network['damaged_lines'] = self.network.get('damaged_lines', 0) + invalid
                    if time.monotonic() - last_status > 3:
                        last_status = time.monotonic()
                        with urlopen(self.rover + '/api/records/status', timeout=2) as response:
                            sd = json.load(response)
                        try:
                            with urlopen(self.rover + '/api/lidar/revolution', timeout=2) as response:
                                latest = json.load(response)
                        except HTTPError as exc:
                            if exc.code != 503:
                                raise
                            latest = None  # LiDAR stopped or no complete scan yet.
                        with urlopen(self.rover + '/api/lidar/status', timeout=2) as response:
                            lidar = json.load(response)
                        with self.lock:
                            self.network.update(connected=True, last_seen=time.time(), error=None)
                            self.network['sd'] = sd
                            self.network['lidar'] = lidar
                            if latest is not None:
                                if self.latest is None or (latest['boot_id'], latest['seq']) != (self.latest['boot_id'], self.latest['seq']):
                                    self.network['scan_received_at'] = time.time()
                                self.latest = latest
                    self.quit.wait(.08 if added else .4)
                except (OSError, ValueError) as exc:
                    with self.lock:
                        self.network.update(connected=False, error=str(exc))
                    self.quit.wait(2)
        finally:
            store.close()

    def process(self):
        last_publish = last_save = 0
        while not self.quit.is_set():
            try:
                if self.ros_session_active():
                    self.quit.wait(.3)
                    continue
                with self.lock:
                    item = None if self.paused else self.store.next_scan(self.last_id)
                    if item:
                        scan_id, record = item
                        pose = self.mapper.add(scan_id, record)
                        with self.store.db:
                            self.store.db.execute('INSERT OR REPLACE INTO local_poses VALUES(?,?,?,?,?)',
                                                  (self.run_id, scan_id, *(pose if pose is not None else (None, None, None))))
                        self.last_id = scan_id
                    if time.monotonic() - last_publish > .5:
                        self.snapshot = self.mapper.snapshot()
                        self.revision += 1
                        last_publish = time.monotonic()
                    if time.monotonic() - last_save > 10 and self.mapper.placed:
                        self.save()
                        last_save = time.monotonic()
                self.quit.wait(.005 if item else .2)
            except Exception as exc:
                with self.lock:
                    self.mapper.status = 'error'
                    self.mapper.reason = f'Mapping stopped: {exc}'
                    self.paused = True
                self.quit.wait(1)

    def state(self):
        with self.lock:
            count = self.store.db.execute('SELECT COUNT(*) FROM scans').fetchone()[0]
            pending = self.store.db.execute('SELECT COUNT(*) FROM scans WHERE id>?', (self.last_id,)).fetchone()[0]
            result = dict(run_id=self.run_id, created=self.created, revision=self.revision, rover=self.rover,
                        network=dict(self.network), paused=self.paused, saved_scans=count, pending=pending,
                        sd_offset=self.store.offset(), latest=self.latest, map=self.snapshot)
            localization = self.localization_snapshot(network=result['network'], scan_count=count)
            ros = self.ros_snapshot() if not localization else None
            if localization:
                result.update(run_id=localization['run_id'], created=localization['created'],
                              revision=localization['saved_at'], map=localization['map'],
                              backend='localization', paused=False,
                              pending=localization['pending'])
            elif ros:
                latest = self.latest or {}
                live_lag = (max(0, latest['seq']-ros['source_seq'])
                            if latest.get('boot_id') == ros.get('source_boot')
                            and isinstance(latest.get('seq'), int)
                            and isinstance(ros.get('source_seq'), int) else 0)
                result.update(run_id=ros['run_id'], created=ros['created'], revision=ros['saved_at'],
                              map=ros['map'], backend='ros', paused=False,
                              pending=live_lag)
                if time.time()-ros['saved_at'] > 5:
                    result['map']['tracking'] = 'offline'
                    result['map']['reason'] = 'ROS stopped · displaying its last saved map'
            return result

    def ros_snapshot(self):
        path = ROOT/'data/ros-map/live.json'
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return None

    def localization_snapshot(self, network=None, scan_count=None):
        mission = read_status(self.mission_dir)
        run_id = mission.get('map_id', '')
        if mission['state'] == 'offline' or not valid_run_id(run_id):
            return None
        try:
            live = json.loads((ROOT/'data/ros-map/localization-live.json').read_text())
            saved = json.loads((ROOT/'data/ros-map'/f'rebuilt-{run_id}.json').read_text())
            if time.time() - live['saved_at'] > 5:
                return None
            saved['run_id'] = run_id
            latest = self.latest or {}
            pending = (max(0, latest['seq']-live['source_seq'])
                       if latest.get('boot_id') == live.get('source_boot')
                       and isinstance(latest.get('seq'), int)
                       and isinstance(live.get('source_seq'), int) else 999)
            return make_localization_view(saved, live, mission, network=network, pending=pending)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save(self):
        with self.lock:
            localization = self.localization_snapshot()
            if localization:
                return json.loads((self.output / (localization['run_id']+'.json')).read_text())
            ros = self.ros_snapshot()
            if ros:
                (self.output / (ros['run_id']+'.json')).write_text(json.dumps(ros, allow_nan=False))
                records = ROOT/'data/ros-map/live.jsonl'
                if records.exists():
                    (self.output / (ros['run_id']+'.jsonl')).write_bytes(records.read_bytes())
                return ros
            result = dict(run_id=self.run_id, created=self.created, saved_at=time.time(),
                          method='incremental_lidar_icp', loop_closure=False,
                          forward_index=self.mapper.forward, clockwise=self.mapper.clockwise,
                          map=self.mapper.snapshot())
            target = self.output / f'{self.run_id}.json'
            temp = target.with_suffix('.tmp')
            temp.write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
            os.replace(temp, target)
            return result

    def new_room(self, forward, clockwise):
        if self.localization_snapshot():
            raise ValueError('Stop saved localization and start ROS mapping before New room')
        if self.ros_snapshot():
            if not 0 <= forward < 360:
                raise ValueError('Forward angle must be 0–359 degrees')
            if time.time()-self.ros_snapshot()['saved_at'] > 5:
                raise ValueError('Start the ROS mapping terminal first')
            self.save()
            path = ROOT/'data/ros-map/request.json'
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(dict(at=time.time(), forward=forward, clockwise=clockwise)))
            os.replace(temp,path)
            return
        if not 0 <= forward < 360:
            raise ValueError('Forward angle must be 0–359 degrees')
        with self.lock:
            self.save()
            self.start_id = self.store.db.execute('SELECT COALESCE(MAX(id),0)+1 FROM scans').fetchone()[0]
            self.run_id, self.created = uuid4().hex[:12], time.time()
            with self.store.db:
                self.store.db.execute('INSERT INTO local_runs VALUES(?,?,?,?,?)',
                                      (self.run_id, self.start_id, self.created, forward, int(clockwise)))
            self.mapper = RoomMapper(forward, clockwise)
            self.last_id = self.start_id - 1
            self.snapshot = self.mapper.snapshot()
            self.paused = False
            self.revision += 1

    def export_records(self, run_id=None):
        ros = self.ros_snapshot()
        if ros and run_id == ros['run_id']:
            return (ROOT/'data/ros-map/live.jsonl').read_text()
        archived = self.output / ((run_id or self.run_id)+'.jsonl')
        if archived.exists():
            return archived.read_text()
        run_id = run_id or self.run_id
        with self.lock:
            rows = self.store.db.execute('''SELECT s.record_json,p.x,p.y,p.yaw
                FROM local_poses p JOIN scans s ON s.id=p.scan_id WHERE p.run_id=? ORDER BY s.id''', (run_id,)).fetchall()
        return '\n'.join(json.dumps(dict(json.loads(raw), map_pose=None if x is None else dict(x_m=x,y_m=y,yaw_rad=yaw),
                                        map_run=run_id), allow_nan=False) for raw,x,y,yaw in rows) + '\n'


def make_handler(service):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, value, kind='application/json', code=200, filename=None):
            body = value.encode() if isinstance(value, str) else value
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            if filename:
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == '/':
                return self.send(STATIC.read_bytes(), 'text/html; charset=utf-8')
            if parsed.path == '/compare':
                return self.send(COMPARE.read_bytes(), 'text/html; charset=utf-8')
            if parsed.path == '/route.js':
                return self.send(ROUTE_SCRIPT.read_bytes(), 'text/javascript; charset=utf-8')
            if parsed.path == '/api/state':
                return self.send(json.dumps(service.state(), allow_nan=False))
            if parsed.path == '/api/export':
                return self.send(json.dumps(service.save(), allow_nan=False), filename=f'pitdivers-{service.run_id}.json')
            if parsed.path == '/api/records/export':
                run_id = parse_qs(parsed.query).get('run',[service.run_id])[0]
                if len(run_id) != 12 or any(c not in '0123456789abcdef' for c in run_id):
                    return self.send('{"error":"Invalid room"}', code=400)
                return self.send(service.export_records(run_id), 'application/x-ndjson', filename=f'pitdivers-{run_id}-records.jsonl')
            if parsed.path == '/api/saved':
                entries = sorted((p for p in service.output.glob('*.json') if valid_run_id(p.stem)),
                                 key=lambda p:p.stat().st_mtime, reverse=True)
                return self.send(json.dumps([dict(id=p.stem, saved_at=p.stat().st_mtime) for p in entries]))
            if parsed.path == '/api/route':
                run = parse_qs(parsed.query).get('id', [''])[0]
                try:
                    return self.send(json.dumps(service.routes.get(run)))
                except ValueError as exc:
                    return self.send(json.dumps(dict(error=str(exc))), code=400)
            if parsed.path == '/api/mission/status':
                return self.send(json.dumps(read_status(service.mission_dir)))
            if parsed.path == '/api/drive/status':
                try:
                    with service.control_lock:
                        with urlopen(service.rover + '/api/status', timeout=.5) as response:
                            return self.send(response.read())
                except (OSError, ValueError) as exc:
                    return self.send(json.dumps(dict(error=str(exc))), code=503)
            if parsed.path == '/api/image':
                name = parse_qs(parsed.query).get('name',[''])[0]
                if Path(name).name == name and name.endswith('.png'):
                    path = service.output / name
                    if path.is_file():
                        return self.send(path.read_bytes(), 'image/png', filename=name)
            if parsed.path == '/map_view.js':
                return self.send((ROOT/'mapping/map_view.js').read_bytes(), 'text/javascript; charset=utf-8')
            if parsed.path == '/api/saved/map':
                run = parse_qs(parsed.query).get('id',[''])[0]
                if len(run) == 12 and all(c in '0123456789abcdef' for c in run):
                    path = service.output / (run + '.json')
                    if path.exists():
                        return self.send(path.read_bytes())
            self.send('{"error":"Not found"}', code=404)

        def do_POST(self):
            # These APIs are for the local dashboard, not cross-site requests.
            origin = self.headers.get('Origin')
            if origin and urlparse(origin).netloc != self.headers.get('Host'):
                return self.send('{"error":"Origin mismatch"}', code=403)
            try:
                length = int(self.headers.get('Content-Length','0'))
                if length > (8_000_000 if self.path == '/api/image' else 4096):
                    raise ValueError('Request too large')
                data = json.loads(self.rfile.read(length) or b'{}')
                if self.path == '/api/image':
                    layer = data.get('layer')
                    run_id = data.get('run_id', '')
                    if layer not in ('room','temperature','humidity') or len(run_id) != 12 or any(c not in '0123456789abcdef' for c in run_id):
                        raise ValueError('Invalid image name')
                    data_url = data.get('image','')
                    if not data_url.startswith('data:image/png;base64,'):
                        raise ValueError('Expected a PNG image')
                    png = base64.b64decode(data_url.split(',',1)[1], validate=True)
                    if not png.startswith(b'\x89PNG\r\n\x1a\n'):
                        raise ValueError('Invalid PNG')
                    name = f'{run_id}-{layer}.png'
                    (service.output / name).write_bytes(png)
                    return self.send(json.dumps(dict(url='/api/image?name='+name)))
                elif self.path == '/api/pause':
                    with service.lock:
                        service.paused = bool(data.get('paused', True))
                elif self.path == '/api/new':
                    service.new_room(int(data.get('forward',0)), bool(data.get('clockwise', True)))
                elif self.path == '/api/save':
                    service.save()
                elif self.path == '/api/route':
                    run = data.get('id', '')
                    if not all(isinstance(data.get(key), (int, float)) and not isinstance(data.get(key), bool)
                               for key in ('x_m', 'y_m')):
                        raise ValueError('Destination needs numeric x_m and y_m')
                    route = service.routes.set(run, float(data['x_m']), float(data['y_m']))
                    return self.send(json.dumps(route))
                elif self.path == '/api/route/clear':
                    service.routes.clear(data.get('id', ''))
                    return self.send('{"ok":true}')
                elif self.path == '/api/mission/start':
                    run_id = data.get('id', '')
                    round_trip = data.get('round_trip', False)
                    if not isinstance(round_trip, bool):
                        raise ValueError('round_trip must be true or false')
                    if not valid_run_id(run_id):
                        raise ValueError('Choose a saved room first')
                    route = service.routes.get(run_id)
                    if not route or not route.get('localization_destination'):
                        raise ValueError('Mark B on the saved map first')
                    mission = read_status(service.mission_dir)
                    if mission['state'] == 'offline':
                        raise ValueError('Start the saved-localization terminal first')
                    if mission['state'] in ('active', 'paused'):
                        raise ValueError('Mission already active; cancel it first')
                    write_command(service.mission_dir, 'start', run_id, round_trip=round_trip)
                    return self.send('{"queued":true}')
                elif self.path == '/api/mission/cancel':
                    mission = read_status(service.mission_dir)
                    write_command(service.mission_dir, 'cancel', mission.get('map_id', ''))
                    try:
                        with service.control_lock:
                            with urlopen(service.rover + '/stop', timeout=.8) as response:
                                response.read()
                        return self.send('{"stop_sent":true}')
                    except OSError as exc:
                        return self.send(json.dumps(dict(stop_sent=False, error=str(exc))), code=503)
                elif self.path == '/api/speed':
                    value = data.get('value')
                    if isinstance(value, bool) or not isinstance(value, int) or not 80 <= value <= 255:
                        raise ValueError('Motor speed must be an integer from 80 to 255')
                    with service.control_lock:
                        with urlopen(service.rover + '/speed?value=' + str(value), timeout=.5) as response:
                            applied = int(response.read().decode('ascii').strip())
                    return self.send(json.dumps(dict(speed=applied)))
                elif self.path == '/api/lidar':
                    action = data.get('action')
                    if action not in ('start', 'stop'):
                        raise ValueError('Invalid LiDAR action')
                    with urlopen(Request(service.rover + '/api/lidar/' + action, data=b'', method='POST'), timeout=2) as response:
                        response.read()
                elif self.path == '/api/drive':
                    direction = data.get('direction')
                    if direction not in ('forward','backward','left','right','stop'):
                        raise ValueError('Invalid direction')
                    request = manual_request(service.rover, direction, data.get('duty'))
                    if read_status(service.mission_dir)['state'] in ('active','paused'):
                        if direction != 'stop':
                            raise ValueError('Cancel automatic travel before manual driving')
                        write_command(service.mission_dir, 'cancel', '')
                    service.drive_quiet_until = time.monotonic() + 1.0
                    with service.control_lock:
                        with urlopen(request, timeout=.8) as response:
                            response.read()
                else:
                    return self.send('{"error":"Not found"}', code=404)
                self.send('{"ok":true}')
            except HTTPError as exc:
                try:detail=json.load(exc).get('error',str(exc))
                except (ValueError,AttributeError):detail=str(exc)
                self.send(json.dumps(dict(error=detail)),code=exc.code)
            except (ValueError, OSError) as exc:
                self.send(json.dumps(dict(error=str(exc))), code=400)
    return Handler


def create_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--rover', default='http://192.168.0.99')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--db', default=str(ROOT/'mapping/room_scans.sqlite3'))
    parser.add_argument('--output', default=str(ROOT/'data/lidar-maps'))
    return parser


def create_server(service, host, port, server_class=ThreadingHTTPServer):
    return server_class((host, port), make_handler(service))


def main():
    args = create_parser().parse_args()
    service = MappingService(args.rover, args.db, args.output)
    server = create_server(service, args.host, args.port)
    service.start()
    print(f'Room map server: http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.quit.set()
        service.save()
        server.server_close()


if __name__ == '__main__':
    main()
