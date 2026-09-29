"""Three-step demo UI; one existing dashboard owns rover scan polling."""
import argparse, json, math, os, ssl, subprocess, threading, time
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.request import urlopen,Request
from urllib.parse import urlparse
from urllib.error import HTTPError
from uuid import uuid4
from autonav_core import Grid
from autonav_io import read_status,write_command
from demo_planner import plan_tour

ROOT=Path(__file__).resolve().parent.parent
DIR=ROOT/'data/demo'; DIR.mkdir(parents=True,exist_ok=True)
DASH='http://127.0.0.1:8767'
FORWARD_OFFSET=2.936  # Existing chassis/LiDAR mounting, raw scan forward index 0.
def read(path):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}
def atomic(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,allow_nan=False),encoding='utf-8');os.replace(tmp,path)
def proxy(path,payload=None):
    req=Request(DASH+path,data=None if payload is None else json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    try:
        with urlopen(req,timeout=4) as r:return json.load(r)
    except HTTPError as exc:
        try:detail=json.load(exc).get('error',str(exc))
        except (ValueError,AttributeError):detail=str(exc)
        raise ValueError(detail) from exc

class Demo:
    def __init__(self):
        self.lock=threading.Lock();self.plan=None
        self.session=read(DIR/'session.json') or {'mode':'idle','map_id':None}
        self.process=None
        self.calibration_rover=None
    def ensure_stack(self):
        status=read(DIR/'stack-status.json')
        if time.time()-status.get('at',0)<3:return
        wslroot='/mnt/'+str(ROOT.drive[0]).lower()+str(ROOT)[2:].replace('\\','/')
        with (DIR/'supervisor.log').open('a') as log:
            self.process=subprocess.Popen(['wsl.exe','-e','python3',wslroot+'/mapping/demo_stack.py'],
                stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    def switch(self,mode,map_id=None):
        atomic(DIR/'stack-command.json',dict(mode=mode,map_id=map_id,nonce=uuid4().hex))
        self.ensure_stack()
        self.session=dict(mode=mode,map_id=map_id,started=time.time())
        atomic(DIR/'session.json',self.session);self.plan=None
    def state(self):
        base=proxy('/api/state'); mission=read_status(ROOT/'data/autonav')
        stack=read(DIR/'stack-status.json')
        if time.time()-stack.get('at',0)>3:stack={'error':'ROS demo process is not running'}
        mode=self.session['mode']; room=None
        if mode=='mapping':
            snap=read(ROOT/'data/ros-map/live.json')
            if snap.get('created',0)>=self.session.get('started',0)-2:room=snap.get('map')
        elif mode=='localization':
            graph=read(ROOT/'data/ros-map'/('rebuilt-'+self.session['map_id']+'.json'))
            room=graph.get('map')
            if base.get('backend')=='localization' and base.get('run_id')==self.session['map_id']:room=base['map']
            elif room:room=dict(room,tracking='waiting',reason='Finding live position on the saved room')
        if room:
            room=dict(room)
            if mode=='mapping':
                snap_age=time.time()-snap.get('saved_at',0)
                if snap_age>3:room.update(tracking='offline',reason='Waiting for current ROS map')
            if mode=='localization' and mission.get('map_id')==self.session['map_id']:
                if mission.get('pose'):room['pose']=mission['pose']
                if not mission.get('localization',{}).get('ready'):room['tracking']='waiting'
            net=base.get('network',{})
            if not net.get('connected') or time.time()-net.get('scan_received_at',0)>2:
                room.update(tracking='offline',reason='Waiting for fresh LiDAR')
            room['heading_offset']=FORWARD_OFFSET
        return dict(session=self.session,stack=stack,room=room,mission=mission,
                    network=base.get('network'),latest=base.get('latest'),plan=self.plan)
    def no_active(self):
        if read_status(ROOT/'data/autonav')['state'] in ('active','paused'):
            raise ValueError('Press STOP before changing the room or route')
    def calibration(self, action=None):
        if action not in (None,'start','heartbeat'):raise ValueError('Invalid calibration action')
        if action=='start':self.no_active()
        if self.calibration_rover is None:self.calibration_rover=proxy('/api/state')['rover'].rstrip('/')
        rover=self.calibration_rover
        path='/api/turn-calibration'+('/'+action if action else '')
        request=Request(rover+path,data=b'' if action else None)
        try:
            # Wi-Fi can occasionally take ~1 s. This is only the HTTP response
            # budget; it does not extend the ESP's 1.5 s motor heartbeat lease.
            with urlopen(request,timeout=2) as response:return json.load(response)
        except HTTPError as exc:
            if exc.code==404:raise ValueError('Flash the gyro-calibration firmware to enable this button') from exc
            try:detail=json.load(exc).get('error',str(exc))
            except (ValueError,AttributeError):detail=str(exc)
            raise ValueError(detail) from exc
        except OSError as exc:
            raise ValueError('Calibration connection interrupted. Press STOP, check rover Wi-Fi, then retry calibration when connected.') from exc
    def begin(self):
        self.no_active()
        proxy('/api/drive',{'direction':'stop'})
        proxy('/api/lidar',{'action':'start'})
        self.switch('mapping')
        return {'ok':True}
    def finish(self):
        self.no_active()
        if self.session['mode']!='mapping':raise ValueError('Start a room scan first')
        proxy('/api/drive',{'direction':'stop'})
        snap=read(ROOT/'data/ros-map/live.json')
        if snap.get('created',0)<self.session['started']-2 or time.time()-snap.get('saved_at',0)>3:
            raise ValueError('Waiting for a fresh room map')
        room=snap['map']
        if len(room.get('cells',[]))<50 or not room.get('path'):raise ValueError('Scan more of the room before saving')
        if room.get('tracking')!='tracking':raise ValueError('Map tracking is uncertain; scan again before saving')
        ident=uuid4().hex[:12];snap['run_id']=ident;snap['forward_offset_rad']=FORWARD_OFFSET
        atomic(ROOT/'data/ros-map'/f'rebuilt-{ident}.json',snap)
        atomic(ROOT/'data/lidar-maps'/f'{ident}.json',snap)
        self.switch('localization',ident)
        return {'ok':True,'map_id':ident}
    def ready_pose(self):
        s=read_status(ROOT/'data/autonav')
        if (s.get('map_id')!=self.session.get('map_id') or not s.get('localization',{}).get('ready')
            or s.get('pose_age_s',99) is None or s.get('pose_age_s',99)>.6
            or s.get('scan_age_s',99) is None or s.get('scan_age_s',99)>.6):
            raise ValueError('Waiting for a fresh, localized rover position')
        return s['pose']
    def preview(self,targets,return_home):
        self.no_active()
        if self.session['mode']!='localization':raise ValueError('Finish the room scan first')
        status=read_status(ROOT/'data/autonav')
        pose=status.get('pose')
        if status.get('map_id')!=self.session['map_id'] or not pose:
            raise ValueError('Waiting for a rover position on this map')
        if not isinstance(return_home,bool):raise ValueError('Invalid return option')
        graph=read(ROOT/'data/ros-map'/f"rebuilt-{self.session['map_id']}.json")
        grid=Grid.from_cells(graph['map']['cells'],graph['map']['resolution'])
        self.plan=plan_tour(grid,pose[:2],targets,return_home)
        self.plan.update(targets=targets,map_id=self.session['map_id'],start=pose[:2])
        return self.plan
    def go(self):
        self.no_active();self.ready_pose()
        if not self.plan:raise ValueError('Plan the route first')
        write_command(ROOT/'data/autonav','start',self.session['map_id'],
                      round_trip=self.plan['return_home'],targets=self.plan['targets'])
        return {'ok':True}

demo=Demo()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,value,status=200,kind='application/json'):
        body=value if isinstance(value,bytes) else json.dumps(value,allow_nan=False).encode()
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        try:
            if self.path=='/':return self.send((ROOT/'mapping/demo.html').read_bytes(),kind='text/html; charset=utf-8')
            if self.path=='/demo.js':return self.send((ROOT/'mapping/demo.js').read_bytes(),kind='text/javascript; charset=utf-8')
            if self.path=='/gamepad.js':return self.send((ROOT/'mapping/gamepad.js').read_bytes(),kind='text/javascript; charset=utf-8')
            if self.path=='/calibration.js':return self.send((ROOT/'mapping/calibration.js').read_bytes(),kind='text/javascript; charset=utf-8')
            if self.path=='/api/calibration':return self.send(demo.calibration())
            if self.path=='/rover-ca.crt':return self.send((DIR/'tls/rover-ca.crt').read_bytes(),kind='application/x-x509-ca-cert')
            if self.path=='/api/state':return self.send(demo.state())
            return self.send({'error':'Not found'},404)
        except (OSError,ValueError,KeyError) as e:self.send({'error':str(e)},503)
    def do_POST(self):
        origin=self.headers.get('Origin')
        if origin and urlparse(origin).netloc!=self.headers.get('Host'):return self.send({'error':'Origin mismatch'},403)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<=size<=4096:raise ValueError('Request too large')
            body=json.loads(self.rfile.read(size) or b'{}')
            if self.path=='/api/stop':return self.send(proxy('/api/mission/cancel',{}))
            if self.path=='/api/drive':return self.send(proxy('/api/drive',body))
            if not demo.lock.acquire(blocking=False):raise ValueError('Finishing the previous action')
            try:
                if self.path=='/api/scan':value=demo.begin()
                elif self.path=='/api/finish':value=demo.finish()
                elif self.path=='/api/plan':value=demo.preview(body.get('targets'),body.get('return_home',True))
                elif self.path=='/api/go':value=demo.go()
                elif self.path=='/api/calibration/start':value=demo.calibration('start')
                elif self.path=='/api/calibration/heartbeat':value=demo.calibration('heartbeat')
                else:return self.send({'error':'Not found'},404)
                self.send(value)
            finally:demo.lock.release()
        except (OSError,ValueError,KeyError) as e:self.send({'error':str(e)},400)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--lan',action='store_true')
    parser.add_argument('--https',action='store_true')
    args=parser.parse_args()
    host='0.0.0.0' if args.lan else '127.0.0.1'
    if args.https:
        secure=ThreadingHTTPServer((host,8769),Handler)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(DIR/'tls/server.crt',DIR/'tls/server.key')
        secure.socket=context.wrap_socket(secure.socket,server_side=True)
        threading.Thread(target=secure.serve_forever,daemon=True).start()
    print('Rover demo: http://127.0.0.1:8768/',flush=True)
    ThreadingHTTPServer((host,8768),Handler).serve_forever()
