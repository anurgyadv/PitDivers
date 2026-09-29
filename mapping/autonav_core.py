"""Hardware-independent occupancy planning and conservative wheel commands."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math

# Faster supervised demo profile. PWM is duty, not calibrated ground speed.
DRIVE_DUTY = 180
TURN_DUTY = 255
ARRIVAL_TOLERANCE_M = .30
TURN_ENTRY_RAD = .65
RECOVERY_STABLE_S = .5


@dataclass(frozen=True)
class MotionInputs:
    pose: tuple[float, float, float]
    pose_age_s: float
    scan_age_s: float
    nearest_front_m: float
    wifi_ok: bool


@dataclass
class RecoveryGate:
    started: float
    good_since: float | None = None

    def update(self, now, healthy):
        if now-self.started > 30.:
            return 'timeout'
        if not healthy:
            self.good_since = None
        elif self.good_since is None:
            self.good_since = now
        return 'resume' if self.good_since is not None and now-self.good_since >= RECOVERY_STABLE_S else 'wait'


@dataclass
class TurnProgress:
    """Measure continuous odometry after an acknowledged wheel command.

    Map corrections must not be counted as physical rotation. Allow startup and
    scan latency, but retain a no-progress stop and an absolute duration bound.
    """
    started: float
    yaw: float
    direction: int
    rotation: float = 0.
    checkpoint: float = 0.
    progress_at: float | None = None

    def __post_init__(self):
        self.progress_at = self.started

    def update(self, now, yaw):
        delta = math.atan2(math.sin(yaw-self.yaw), math.cos(yaw-self.yaw))
        self.rotation += delta * self.direction
        self.yaw = yaw
        if self.rotation < self.checkpoint-.05:
            return 'Turn moved opposite to commanded direction'
        if self.rotation-self.checkpoint >= .015:
            self.checkpoint, self.progress_at = self.rotation, now
        if now-self.started >= 15.:
            return 'Turn exceeded 15-second limit'
        if now-self.progress_at >= 2.:
            return 'Turn stalled: no measured rotation for 2 seconds'
        return None


class Grid:
    def __init__(self, cells: dict[tuple[int, int], int], resolution: float):
        if not math.isfinite(resolution) or resolution <= 0:
            raise ValueError('Invalid map resolution')
        self.cells = cells
        self.resolution = resolution

    @classmethod
    def from_cells(cls, cells: list[list[int]], resolution: float) -> 'Grid':
        return cls({(int(x), int(y)): int(value) for x, y, value in cells}, resolution)

    def cell(self, point: tuple[float, float]) -> tuple[int, int]:
        return math.floor(point[0] / self.resolution), math.floor(point[1] / self.resolution)

    def centre(self, cell: tuple[int, int]) -> tuple[float, float]:
        return ((cell[0] + .5) * self.resolution, (cell[1] + .5) * self.resolution)

    def open_cell(self, cell: tuple[int, int], clearance_m: float) -> bool:
        if self.cells.get(cell) != -8:
            return False
        radius = math.ceil(max(0, clearance_m) / self.resolution)
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if math.hypot(dx, dy) * self.resolution <= clearance_m + 1e-9:
                    if self.cells.get((cell[0] + dx, cell[1] + dy)) != -8:
                        return False
        return True

    def is_free(self, x: float, y: float, clearance_m: float) -> bool:
        return self.open_cell(self.cell((x, y)), clearance_m)

    def segment_free(self, start, end, clearance_m):
        steps = max(1, math.ceil(math.dist(start, end) / (self.resolution / 3)))
        return all(self.is_free(start[0]+(end[0]-start[0])*i/steps,
                                start[1]+(end[1]-start[1])*i/steps, clearance_m)
                   for i in range(steps+1))

    def smooth(self, path, clearance_m):
        """Shortcut grid stair steps only where the whole footprint stays free."""
        if len(path) < 3:
            return path
        corners, i = [path[0]], 0
        while i < len(path)-1:
            j = len(path)-1
            while j > i+1 and not self.segment_free(path[i], path[j], clearance_m):
                j -= 1
            corners.append(path[j])
            i = j
        result = [corners[0]]
        for a,b in zip(corners,corners[1:]):
            n = max(1, math.ceil(math.dist(a,b)/self.resolution))
            result.extend((a[0]+(b[0]-a[0])*i/n, a[1]+(b[1]-a[1])*i/n)
                          for i in range(1,n+1))
        return result

    def plan(self, start: tuple[float, float], goal: tuple[float, float],
             clearance_m: float = .18) -> list[tuple[float, float]]:
        source, target = self.cell(start), self.cell(goal)
        if not self.open_cell(source, clearance_m) or not self.open_cell(target, clearance_m):
            raise ValueError('Start or destination is not in observed free space')
        neighbours = ((1, 0), (-1, 0), (0, 1), (0, -1),
                      (1, 1), (1, -1), (-1, 1), (-1, -1))
        best = {source: 0.0}
        previous = {}
        queue = [(math.dist(source, target), 0.0, source)]
        while queue:
            _, cost, current = heapq.heappop(queue)
            if cost > best[current] + 1e-9:
                continue
            if current == target:
                result = [target]
                while result[-1] != source:
                    result.append(previous[result[-1]])
                return [self.centre(cell) for cell in reversed(result)]
            for dx, dy in neighbours:
                other = current[0] + dx, current[1] + dy
                if not self.open_cell(other, clearance_m):
                    continue
                if dx and dy and (not self.open_cell((current[0] + dx, current[1]), clearance_m)
                                  or not self.open_cell((current[0], current[1] + dy), clearance_m)):
                    continue
                new_cost = cost + math.hypot(dx, dy)
                if new_cost < best.get(other, math.inf):
                    best[other] = new_cost
                    previous[other] = current
                    heapq.heappush(queue, (new_cost + math.dist(other, target), new_cost, other))
        raise ValueError('No path through observed free space')

    def plan_from_nearby(self, start: tuple[float, float], goal: tuple[float, float],
                         clearance_m: float, start_clearance_m: float = .18,
                         tolerance_m: float = .10) -> list[tuple[float, float]]:
        """Join a nearby clear route only through observed space around the rover."""
        if not self.is_free(*start, start_clearance_m):
            raise ValueError('Rover is not in observed free space')
        if self.is_free(*start, clearance_m):
            return self.plan(start, goal, clearance_m)
        radius = math.ceil(tolerance_m / self.resolution)
        sx, sy = self.cell(start)
        candidates = []
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                point = self.centre((sx + dx, sy + dy))
                distance = math.dist(start, point)
                if distance <= tolerance_m and self.is_free(*point, clearance_m):
                    candidates.append((distance, point))
        for _, point in sorted(candidates):
            steps = max(1, math.ceil(math.dist(start, point) / (self.resolution / 2)))
            if not all(self.is_free(start[0] + (point[0]-start[0])*i/steps,
                                    start[1] + (point[1]-start[1])*i/steps,
                                    start_clearance_m) for i in range(steps + 1)):
                continue
            try:
                return self.plan(point, goal, clearance_m)
            except ValueError:
                continue
        raise ValueError('Rover is outside the saved map’s clear route')


def estimate_forward_offset(path: list[list[float]]) -> float:
    """Infer rover-forward bearing minus LiDAR/TF yaw from a forward taught pass."""
    errors = []
    step = 20
    for index in range(0, len(path)-step, 10):
        first, second = path[index], path[index+step]
        dx, dy = second[0]-first[0], second[1]-first[1]
        if math.hypot(dx, dy) < .1:
            continue
        yaw_change = math.atan2(math.sin(second[2]-first[2]), math.cos(second[2]-first[2]))
        if abs(yaw_change) > .25:
            continue
        errors.append(math.atan2(dy, dx)-first[2])
    if len(errors) < 10:
        raise ValueError('Saved teaching pass cannot calibrate the forward axis')
    cosine = sum(math.cos(value) for value in errors)
    sine = sum(math.sin(value) for value in errors)
    if math.hypot(cosine, sine) / len(errors) < .8:
        raise ValueError('Saved teaching pass has inconsistent forward heading')
    return math.atan2(sine, cosine)


def motion_command(inputs: MotionInputs, target: tuple[float, float],
                   reverse: bool = False) -> tuple[int, int]:
    """Return signed channel A/B duty. A is the reversed physical right side."""
    x, y, yaw = inputs.pose
    if (not inputs.wifi_ok or inputs.pose_age_s > .6 or inputs.scan_age_s > .6
            or inputs.nearest_front_m < .45 or not all(map(math.isfinite, (x, y, yaw)))):
        return 0, 0
    distance = math.hypot(target[0] - x, target[1] - y)
    if distance < .12:
        return 0, 0
    heading = math.atan2(target[1] - y, target[0] - x)
    if reverse:
        yaw += math.pi
    error = math.atan2(math.sin(heading - yaw), math.cos(heading - yaw))
    if abs(error) > .75:  # No in-place spin: this chassis stalls during one.
        return 0, 0
    inner = max(0, min(DRIVE_DUTY, round(DRIVE_DUTY * (1 - abs(error) * 160 / 150))))
    if reverse:
        if error > 0:
            return inner, -DRIVE_DUTY
        return DRIVE_DUTY, -inner
    if error > 0:
        return -DRIVE_DUTY, inner
    return -inner, DRIVE_DUTY


def turn_command(inputs: MotionInputs, target: tuple[float, float],
                 sweep_clearance_m: float, reverse=False) -> tuple[int, int]:
    """Bounded supervisor calls this only while verifying yaw progress."""
    if (not inputs.wifi_ok or inputs.pose_age_s > .6 or inputs.scan_age_s > .6
            or not math.isfinite(sweep_clearance_m) or sweep_clearance_m < .45
            or not all(map(math.isfinite, inputs.pose))):
        return 0, 0
    x,y,yaw = inputs.pose
    heading = math.atan2(target[1]-y, target[0]-x)
    if reverse:
        yaw += math.pi
    error = math.atan2(math.sin(heading-yaw), math.cos(heading-yaw))
    if abs(error) < .20:
        return 0, 0
    return (-TURN_DUTY, -TURN_DUTY) if error > 0 else (TURN_DUTY, TURN_DUTY)
