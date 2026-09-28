"""Present a saved ROS map with the live, separately localized rover pose."""

from __future__ import annotations

import math
import time


def make_localization_view(saved: dict, live: dict, mission: dict,
                           network: dict | None = None, pending: int = 0,
                           now: float | None = None) -> dict:
    saved_map, live_map = saved['map'], live['map']
    now = time.time() if now is None else now
    scan_age = mission.get('scan_age_s')
    pose_age = mission.get('pose_age_s')
    ros_fresh = (isinstance(scan_age, (int, float)) and math.isfinite(scan_age)
                 and scan_age <= 2 and isinstance(pose_age, (int, float))
                 and math.isfinite(pose_age) and pose_age <= 2
                 and live_map.get('tracking') == 'tracking')
    link_fresh = network is None or (
        network.get('connected') and network.get('lidar', {}).get('running')
        and isinstance(network.get('last_seen'), (int, float))
        and now - network['last_seen'] <= 8
        and isinstance(network.get('scan_received_at'), (int, float))
        and now - network['scan_received_at'] <= 6)
    fresh = ros_fresh and link_fresh and pending <= 20
    tracking = 'tracking' if fresh else 'waiting' if ros_fresh and link_fresh else 'offline'
    reason = ('Localizing on saved room · geometry fixed; rover pose and scan live'
              if fresh else
              f'Catching up {pending} recorded scans · position is delayed'
              if tracking == 'waiting' else
              live_map.get('reason') or 'Localization stale or rover offline · showing last known position')
    map_view = dict(saved_map)
    map_view.update(
        pose=live_map['pose'],
        points=live_map.get('points', []),
        live_path=live_map.get('path', []),
        environment=saved_map.get('environment', []) + live_map.get('environment', []),
        tracking=tracking,
        reason=reason,
    )
    return dict(run_id=saved['run_id'], created=saved['created'],
                saved_at=live['saved_at'], last_id=live['last_id'],
                pending=pending, map=map_view, backend='localization')
