"""Publish WSL snapshots across a Windows file lock without ending ROS."""

from __future__ import annotations

import os
import json
from pathlib import Path
import time


def replace_with_retry(temp: str | Path, target: str | Path,
                       attempts: int = 20, delay_s: float = .05) -> bool:
    for attempt in range(attempts):
        try:
            os.replace(temp, target)
            return True
        except PermissionError:
            if attempt + 1 < attempts:
                time.sleep(delay_s)
    return False


def write_json_snapshot(target: str | Path, value: dict) -> bool:
    """A locked Windows reader can delay a heartbeat, never terminate its owner."""
    target = Path(target)
    temp = target.with_suffix('.tmp')
    try:
        temp.write_text(json.dumps(value, allow_nan=False), encoding='utf-8')
        return replace_with_retry(temp, target)
    except PermissionError:
        return False  # Retry with a fresh heartbeat on the next supervisor tick.
