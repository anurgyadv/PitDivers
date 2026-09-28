"""Saved, map-specific hallway destination and taught-path preview."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path


def valid_run_id(run_id: str) -> bool:
    return len(run_id) == 12 and all(c in "0123456789abcdef" for c in run_id)


def build_route(saved_map: dict, x: float, y: float) -> dict:
    """Snap a chosen destination to the recorded path and return its round trip."""
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("Destination coordinates must be finite")
    path = saved_map.get("map", {}).get("path") or []
    if len(path) < 2:
        raise ValueError("This saved map has no usable rover path")
    index = min(range(len(path)), key=lambda i: math.hypot(path[i][0] - x, path[i][1] - y))
    snap_m = math.hypot(path[index][0] - x, path[index][1] - y)
    if snap_m > 0.5:
        raise ValueError("Choose a point within 0.5 m of the recorded rover path")
    if index == 0:
        raise ValueError("Choose a destination away from the starting point")
    outward = path[: index + 1]
    distance_m = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(outward, outward[1:]))
    if distance_m < 0.5:
        raise ValueError("Choose a destination at least 0.5 m along the path")
    return {
        "map_id": saved_map["run_id"],
        "start": {"x_m": path[0][0], "y_m": path[0][1], "yaw_rad": path[0][2]},
        "destination": {"x_m": path[index][0], "y_m": path[index][1],
                        "yaw_rad": path[index][2], "path_index": index},
        "clicked": {"x_m": x, "y_m": y},
        "snap_m": round(snap_m, 3),
        "outward_m": round(distance_m, 3),
        "round_trip_m": round(distance_m * 2, 3),
        "path": [[p[0], p[1]] for p in outward],
        "mode": "preview_only",
    }


class RouteStore:
    def __init__(self, maps_dir: str | Path, routes_dir: str | Path):
        self.maps_dir = Path(maps_dir)
        self.routes_dir = Path(routes_dir)

    def map(self, run_id: str) -> dict:
        if not valid_run_id(run_id):
            raise ValueError("Invalid room ID")
        try:
            return json.loads((self.maps_dir / f"{run_id}.json").read_text())
        except FileNotFoundError:
            raise ValueError("Saved room not found") from None

    def get(self, run_id: str) -> dict | None:
        self.map(run_id)
        path = self.routes_dir / f"{run_id}.json"
        try:
            route = json.loads(path.read_text())
            return self._with_localization_pose(run_id, route)
        except FileNotFoundError:
            return None

    def _with_localization_pose(self, run_id: str, route: dict) -> dict:
        """Match B by scan ID because a graph replay can shift its map frame."""
        rebuilt = self.maps_dir.parent / 'ros-map' / f'rebuilt-{run_id}.json'
        try:
            graph_map = json.loads(rebuilt.read_text())
            source_path = self.map(run_id)['map']['path']
            scan_id = source_path[route['destination']['path_index']][3]
            pose = next(p for p in graph_map['map']['path'] if p[3] == scan_id)
        except (OSError, KeyError, IndexError, StopIteration, ValueError):
            route['localization_destination'] = None
            return route
        route['localization_destination'] = {
            'x_m': pose[0], 'y_m': pose[1], 'yaw_rad': pose[2], 'scan_id': scan_id,
        }
        route['map_frame_difference_m'] = round(math.hypot(
            pose[0] - route['destination']['x_m'],
            pose[1] - route['destination']['y_m']), 3)
        return route

    def set(self, run_id: str, x: float, y: float) -> dict:
        saved_map = self.map(run_id)
        route = self._with_localization_pose(run_id, build_route(saved_map, x, y))
        self.routes_dir.mkdir(parents=True, exist_ok=True)
        target = self.routes_dir / f"{run_id}.json"
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(route, indent=2) + "\n")
        os.replace(temp, target)
        return route

    def clear(self, run_id: str) -> None:
        self.map(run_id)
        (self.routes_dir / f"{run_id}.json").unlink(missing_ok=True)
