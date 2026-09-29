"""WSL process owner for the demo; switching modes never starts wheel travel."""
import json, os, signal, subprocess, time
from pathlib import Path
from atomic_snapshot import write_json_snapshot
ROOT=Path(__file__).resolve().parent.parent
DIR=ROOT/'data/demo'; DIR.mkdir(parents=True,exist_ok=True)
child=None; mode='idle'; seen=''; error=None
def read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}
def stop():
    global child
    if child and child.poll() is None:
        os.killpg(child.pid,signal.SIGINT if mode=='mapping' else signal.SIGTERM)
        try:child.wait(12)
        except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
    child=None
def terminate(*args):raise KeyboardInterrupt
signal.signal(signal.SIGTERM,terminate)
try:
    while True:
        cmd=read(DIR/'stack-command.json')
        if cmd.get('nonce') and cmd['nonce']!=seen:
            seen=cmd['nonce']; stop();mode=cmd['mode'];error=None
            if mode not in ('mapping','localization','idle'):raise ValueError('Unknown demo mode')
            if mode!='idle':
                args=['bash',str(ROOT/'mapping'/('start_ros_mapping.sh' if mode=='mapping' else 'start_auto_localization.sh'))]
                if mode=='localization':args.append(cmd['map_id'])
                with (DIR/'ros.log').open('w') as log:
                    child=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,
                                           env={**os.environ,'PITDIVERS_SEED_CURRENT':'1'})
        if child and child.poll() is not None:error=f'ROS exited ({child.returncode}); inspect data/demo/ros.log'
        write_json_snapshot(DIR/'stack-status.json',
                            dict(at=time.time(),mode=mode,pid=os.getpid(),error=error,nonce=seen))
        time.sleep(.4)
except KeyboardInterrupt:pass
finally:stop()
