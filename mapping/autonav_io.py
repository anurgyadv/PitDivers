"""Atomic dashboard-to-ROS mission commands and fresh status reads."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from uuid import uuid4


def read_status(directory: str | Path) -> dict:
    try:
        data = json.loads((Path(directory)/'status.json').read_text())
        if time.time() - float(data['at']) <= 2 and data.get('state'):
            return data
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {'state': 'offline', 'reason': 'Start the saved-localization terminal'}


def write_command(directory: str | Path, action: str, map_id: str,
                  round_trip: bool = False, targets=None) -> dict:
    if action not in ('start', 'cancel'):
        raise ValueError('Invalid mission action')
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    command = {'action': action, 'map_id': map_id, 'round_trip': round_trip,
               'nonce': uuid4().hex, 'at': time.time()}
    if targets is not None:
        from demo_planner import validate_points
        command['targets']=validate_points(targets)
    temp = path / 'command.tmp'
    temp.write_text(json.dumps(command))
    os.replace(temp, path / 'command.json')
    return command
