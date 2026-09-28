"""Run in sourced WSL; supervise ROS nodes and dashboard new-room requests."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
WORK = Path.home()/'pitdivers_ros'
DB = WORK/'room_scans.sqlite3'
OUT = ROOT/'data/ros-map'
OUT.mkdir(parents=True, exist_ok=True)
(WORK/'logs').mkdir(exist_ok=True)
children = []
handles = []

def start(args, name):
    log = (WORK/'logs'/f'{name}.log').open('w')
    handles.append(log)
    child = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    children.append(child)

def stop_nodes():
    for child in children:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGINT)
    for child in children:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
    children.clear()
    for log in handles:
        log.close()
    handles.clear()

request = OUT/'request.json'
seen = request.read_text() if request.exists() else ''
session = OUT/'mapping-session.json'
rover = os.environ.get('PITDIVERS_ROVER_URL', 'http://192.168.0.99')

def launch(after_id=0, forward=0, clockwise=True):
    start(['ros2','launch','rf2o_laser_odometry','rf2o_laser_odometry.launch.py'], 'rf2o')
    start(['ros2','launch','slam_toolbox','online_async_launch.py',
           'slam_params_file:='+str(ROOT/'mapping/slam.yaml')], 'slam')
    time.sleep(5)
    command = [sys.executable,str(ROOT/'mapping/ros_bridge.py'),'--db',str(DB),
               '--output',str(OUT/'live.json'),'--after-id',str(after_id),
               '--live-file',str(OUT/'latest-rover.json'),
               '--resume-after-gap','--forward-index',str(forward)]
    if not clockwise:
        command.append('--counterclockwise')
    start(command,'bridge')

try:
    session.write_text(json.dumps({'at':time.time(),'mode':'mapping'}))
    launch()
    print('ROS map ready for dashboard. New room resets ROS without moving the rover.', flush=True)
    while True:
        text = request.read_text() if request.exists() else ''
        if text != seen:
            data = json.loads(text)
            seen = text
            stop_nodes()
            launch(0, int(data.get('forward',0)), bool(data.get('clockwise',True)))
        if any(child.poll() is not None for child in children):
            raise RuntimeError('A ROS process exited; inspect ~/pitdivers_ros/logs')
        try:
            session.write_text(json.dumps({'at':time.time(),'mode':'mapping'}))
        except OSError:
            pass
        time.sleep(.5)
except KeyboardInterrupt:
    pass
finally:
    stop_nodes()
    try:
        session.unlink(missing_ok=True)
    except OSError:
        pass
