"""Small bounded targets for ESP control; no Wi-Fi per gyro sample."""
import json
import math
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError


class OnboardClient:
    def __init__(self, rover, forward_offset):
        self.rover=rover.rstrip('/')
        # ros_bridge defaults: forward_index=0, clockwise raw angles.
        self.front=round(-math.degrees(forward_offset))%360
        self.sequence=int(time.time_ns())%0x7ffffffe+1
        self.turn_id=None
        self.started=0.

    def request(self,path,values=None):
        req=Request(self.rover+path+('?' + urlencode(values) if values is not None else ''),
                    data=b'' if values is not None else None)
        try:
            with urlopen(req,timeout=.4) as response:return json.load(response)
        except HTTPError as exc:
            try:reason=json.load(exc).get('error',str(exc))
            except (ValueError,AttributeError):reason=str(exc)
            raise OSError(reason) from exc

    def status(self):
        v=self.request('/api/motion/status')
        if v.get('version')!=1:raise OSError('Unsupported ESP motion protocol')
        if v.get('control_age_ms',999)>100:raise OSError('ESP control task is stale')
        return v

    def next_id(self):
        self.sequence=self.sequence%0x7ffffffe+1
        return self.sequence

    def turn(self,degrees):
        if not math.isfinite(degrees) or not 1<=abs(degrees)<=180:raise ValueError('Invalid turn angle')
        # End any translation before accepting one indivisible, bounded turn.
        with urlopen(self.rover+'/stop',timeout=.4) as response:response.read()
        deadline=time.monotonic()+.35
        while True:
            v=self.status()
            if v['mode']=='idle':break
            if time.monotonic()>deadline:raise OSError('ESP did not stop before turn')
            time.sleep(.015)
        if not v.get('ready'):raise OSError('Use Calibrate turns after flashing or restarting ESP')
        self.turn_id=self.next_id();self.started=time.monotonic()
        result=self.request('/api/motion',dict(kind='turn',id=self.turn_id,angle=round(degrees,3),front=self.front))
        if result.get('id')!=self.turn_id:raise OSError('ESP did not acknowledge turn id')

    def poll_turn(self):
        if self.turn_id is None:raise OSError('No ESP turn in progress')
        v=self.request('/api/motion/heartbeat',dict(id=self.turn_id))
        if v.get('control_age_ms',999)>100:raise OSError('ESP control task is stale')
        if v.get('id')!=self.turn_id:
            if time.monotonic()-self.started<.5:return dict(v,mode='pending')
            raise OSError('ESP lost the active turn command')
        if v.get('mode')=='fault':raise OSError(v.get('reason','ESP stopped turn'))
        if v.get('mode') not in ('turn','done'):raise OSError('ESP turn was stopped')
        if time.monotonic()-self.started>16:raise OSError('ESP turn exceeded host deadline')
        return v

    def hold(self,error_degrees,duty):
        if not math.isfinite(error_degrees) or abs(error_degrees)>40:raise ValueError('Heading correction out of range')
        if duty==0 or abs(duty)>200:raise ValueError('Drive duty out of range')
        result=self.request('/api/motion',dict(kind='hold',id=self.next_id(),angle=round(error_degrees,3),duty=duty,front=self.front))
        if not result.get('queued'):raise OSError('ESP did not acknowledge heading command')
