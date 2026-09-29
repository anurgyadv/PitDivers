from __future__ import annotations

import json
import math
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


MAP_SCHEMA_VERSION = 1
ACTION_TYPES = {
    "take_photo",
    "temperature",
    "humidity",
    "distance_scan",
    "vibration_scan",
    "wait",
    "return_home",
}


class Point(BaseModel):
    x: float
    y: float


class TeachPose(Point):
    yaw_deg: float = 0.0
    timestamp_s: float | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class MapObstacle(BaseModel):
    id: str
    name: str = "Obstacle"
    polygon: list[Point] = Field(min_length=3)


class WaypointAction(BaseModel):
    type: Literal[
        "take_photo",
        "temperature",
        "humidity",
        "distance_scan",
        "vibration_scan",
        "wait",
        "return_home",
    ]
    duration_s: float = Field(default=0.0, ge=0.0, le=3600.0)
    parameters: dict[str, Any] = Field(default_factory=dict)


class RouteWaypoint(Point):
    id: str
    name: str = "Waypoint"
    heading_deg: float | None = None
    speed_mps: float = Field(default=0.3, gt=0.0, le=3.0)
    tolerance_m: float = Field(default=0.2, gt=0.0, le=2.0)
    actions: list[WaypointAction] = Field(default_factory=list)
    semantic_object_id: str | None = None


class RoverMap(BaseModel):
    schema_version: int = MAP_SCHEMA_VERSION
    id: str = ""
    name: str = Field(default="Untitled mission", min_length=1, max_length=120)
    frame_id: str = "map"
    units: Literal["metres"] = "metres"
    width_m: float = Field(default=10.0, gt=0.0, le=10_000.0)
    height_m: float = Field(default=8.0, gt=0.0, le=10_000.0)
    grid_m: float = Field(default=0.5, gt=0.0, le=100.0)
    rover_radius_m: float = Field(default=0.18, gt=0.0, le=5.0)
    boundary: list[Point] = Field(default_factory=list)
    obstacles: list[MapObstacle] = Field(default_factory=list)
    teach_trace: list[TeachPose] = Field(default_factory=list)
    route: list[RouteWaypoint] = Field(default_factory=list)
    source_capture: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _xy(point: Point) -> tuple[float, float]:
    return float(point.x), float(point.y)


def _cross(a: Point, b: Point, c: Point) -> float:
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)


def _on_segment(a: Point, b: Point, p: Point, epsilon: float = 1e-9) -> bool:
    return (
        min(a.x, b.x) - epsilon <= p.x <= max(a.x, b.x) + epsilon
        and min(a.y, b.y) - epsilon <= p.y <= max(a.y, b.y) + epsilon
        and abs(_cross(a, b, p)) <= epsilon
    )


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    ab_c, ab_d = _cross(a, b, c), _cross(a, b, d)
    cd_a, cd_b = _cross(c, d, a), _cross(c, d, b)
    if ((ab_c > 0 > ab_d) or (ab_c < 0 < ab_d)) and (
        (cd_a > 0 > cd_b) or (cd_a < 0 < cd_b)
    ):
        return True
    return any(
        (
            abs(value) <= 1e-9 and _on_segment(start, end, point)
            for value, start, end, point in (
                (ab_c, a, b, c),
                (ab_d, a, b, d),
                (cd_a, c, d, a),
                (cd_b, c, d, b),
            )
        )
    )


def point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    if len(polygon) < 3:
        return False
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if _on_segment(previous, current, point):
            return True
        crosses = (current.y > point.y) != (previous.y > point.y)
        if crosses:
            x_at_y = (previous.x - current.x) * (point.y - current.y) / (
                previous.y - current.y
            ) + current.x
            if point.x < x_at_y:
                inside = not inside
        previous = current
    return inside


def _segment_hits_polygon(a: Point, b: Point, polygon: list[Point]) -> bool:
    if point_in_polygon(a, polygon) or point_in_polygon(b, polygon):
        return True
    return any(
        segments_intersect(a, b, polygon[index - 1], polygon[index])
        for index in range(len(polygon))
    )


def _distance(a: Point, b: Point) -> float:
    return math.hypot(b.x - a.x, b.y - a.y)


def validate_map(rover_map: RoverMap) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if rover_map.schema_version != MAP_SCHEMA_VERSION:
        errors.append(
            f"Unsupported schema version {rover_map.schema_version}; expected {MAP_SCHEMA_VERSION}."
        )
    if len(rover_map.boundary) < 3:
        errors.append("Draw an operating boundary with at least three points.")

    collections: list[tuple[str, list[Point]]] = [("boundary", rover_map.boundary)]
    collections.extend((f"obstacle {item.name}", item.polygon) for item in rover_map.obstacles)
    for label, points in collections:
        for point in points:
            if not (0 <= point.x <= rover_map.width_m and 0 <= point.y <= rover_map.height_m):
                errors.append(
                    f"A point in {label} lies outside the {rover_map.width_m:g} m × {rover_map.height_m:g} m map."
                )
                break

    if len(rover_map.route) < 2:
        errors.append("Add at least two route waypoints.")

    for index, waypoint in enumerate(rover_map.route, start=1):
        if rover_map.boundary and not point_in_polygon(waypoint, rover_map.boundary):
            errors.append(f"Waypoint {index} is outside the operating boundary.")
        for obstacle in rover_map.obstacles:
            if point_in_polygon(waypoint, obstacle.polygon):
                errors.append(f"Waypoint {index} is inside obstacle ‘{obstacle.name}’.")

    for index in range(1, len(rover_map.route)):
        start, end = rover_map.route[index - 1], rover_map.route[index]
        if _distance(start, end) < 0.01:
            errors.append(f"Waypoints {index} and {index + 1} occupy the same position.")
        for obstacle in rover_map.obstacles:
            if _segment_hits_polygon(start, end, obstacle.polygon):
                errors.append(
                    f"Route segment {index}→{index + 1} crosses obstacle ‘{obstacle.name}’."
                )

    low_confidence = sum(pose.confidence < 0.5 for pose in rover_map.teach_trace)
    if low_confidence:
        warnings.append(f"{low_confidence} teach-trace poses have localisation confidence below 50%.")
    if not rover_map.teach_trace:
        warnings.append("No teach trace is attached; route alignment cannot be compared with a manual run.")
    if rover_map.route and rover_map.route[0].actions:
        warnings.append("Actions on the first waypoint run as soon as the mission starts.")

    route_length = sum(
        _distance(rover_map.route[index - 1], rover_map.route[index])
        for index in range(1, len(rover_map.route))
    )
    action_count = sum(len(waypoint.actions) for waypoint in rover_map.route)
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "route_length_m": round(route_length, 3),
            "waypoint_count": len(rover_map.route),
            "action_count": action_count,
            "obstacle_count": len(rover_map.obstacles),
            "teach_pose_count": len(rover_map.teach_trace),
        },
    }


def compile_plan(rover_map: RoverMap) -> dict[str, Any]:
    report = validate_map(rover_map)
    if not report["valid"]:
        raise ValueError("Mission is unsafe: " + " ".join(report["errors"]))

    commands: list[dict[str, Any]] = []
    eta_s = 0.0
    previous: RouteWaypoint | None = None
    for index, waypoint in enumerate(rover_map.route):
        travel_m = _distance(previous, waypoint) if previous is not None else 0.0
        travel_s = travel_m / waypoint.speed_mps if travel_m else 0.0
        eta_s += travel_s
        commands.append(
            {
                "sequence": len(commands) + 1,
                "command": "MOVE_TO",
                "waypoint_id": waypoint.id,
                "waypoint_index": index,
                "x_m": round(waypoint.x, 4),
                "y_m": round(waypoint.y, 4),
                "heading_deg": waypoint.heading_deg,
                "speed_mps": waypoint.speed_mps,
                "arrival_tolerance_m": waypoint.tolerance_m,
                "segment_length_m": round(travel_m, 4),
                "estimated_duration_s": round(travel_s, 3),
            }
        )
        for action in waypoint.actions:
            duration_s = action.duration_s
            eta_s += duration_s
            commands.append(
                {
                    "sequence": len(commands) + 1,
                    "command": action.type.upper(),
                    "waypoint_id": waypoint.id,
                    "duration_s": duration_s,
                    "parameters": action.parameters,
                }
            )
        previous = waypoint

    return {
        "schema_version": 1,
        "mission_id": rover_map.id,
        "mission_name": rover_map.name,
        "frame_id": rover_map.frame_id,
        "units": rover_map.units,
        "generated_at": _now(),
        "safety": {
            "require_localisation": True,
            "stay_inside_boundary": True,
            "obstacle_stop_distance_m": 0.30,
            "maximum_pose_age_s": 0.50,
        },
        "boundary": [point.model_dump() for point in rover_map.boundary],
        "obstacles": [obstacle.model_dump() for obstacle in rover_map.obstacles],
        "commands": commands,
        "summary": {
            **report["metrics"],
            "command_count": len(commands),
            "estimated_duration_s": round(eta_s, 2),
        },
    }


class MapStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.RLock()

    @staticmethod
    def slug(value: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return cleaned[:64] or "mission"

    def _path(self, map_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", map_id):
            raise ValueError("Invalid map identifier")
        return self.root / f"{map_id}.json"

    def list(self) -> list[dict[str, Any]]:
        self.root.mkdir(parents=True, exist_ok=True)
        result: list[dict[str, Any]] = []
        for path in self.root.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                rover_map = RoverMap.model_validate(payload)
                report = validate_map(rover_map)
                result.append(
                    {
                        "id": rover_map.id,
                        "name": rover_map.name,
                        "updated_at": rover_map.updated_at,
                        "valid": report["valid"],
                        **report["metrics"],
                    }
                )
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return sorted(result, key=lambda item: item.get("updated_at") or "", reverse=True)

    def get(self, map_id: str) -> RoverMap:
        path = self._path(map_id)
        if not path.is_file():
            raise FileNotFoundError(map_id)
        return RoverMap.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, rover_map: RoverMap, requested_id: str | None = None) -> RoverMap:
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            base_id = self.slug(requested_id or rover_map.id or rover_map.name)
            map_id = base_id
            if not requested_id and not rover_map.id:
                counter = 2
                while self._path(map_id).exists():
                    map_id = f"{base_id[:58]}-{counter}"
                    counter += 1
            existing_created_at = None
            try:
                existing_created_at = self.get(map_id).created_at
            except FileNotFoundError:
                pass
            now = _now()
            saved = rover_map.model_copy(
                update={
                    "id": map_id,
                    "created_at": rover_map.created_at or existing_created_at or now,
                    "updated_at": now,
                }
            )
            target = self._path(map_id)
            temporary = target.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(saved.model_dump(mode="json"), indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(target)
            return saved
