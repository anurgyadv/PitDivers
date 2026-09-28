"""Publish WSL snapshots across a Windows file lock without ending ROS."""

from __future__ import annotations

import os
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
