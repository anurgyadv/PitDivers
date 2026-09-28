"""Conservative 2-D scan matching and occupancy mapping for the local dashboard.

This is incremental odometry, not a loop-closing SLAM optimizer. Failed fits are
left unplaced. Temperature belongs at the rover, never at LiDAR wall endpoints.
"""
from collections import deque
import math

import numpy as np
from scipy.spatial import cKDTree


def scan_points(record, forward=0, clockwise=True):
    ranges = np.asarray(record['ranges_mm'], dtype=float) / 1000
    angle = np.deg2rad(np.arange(360) - forward) * (-1 if clockwise else 1)
    valid = (ranges >= .08) & (ranges <= 6)
    return np.column_stack((ranges[valid] * np.cos(angle[valid]), ranges[valid] * np.sin(angle[valid])))


def transform(points, pose):
    c, s = math.cos(pose[2]), math.sin(pose[2])
    return points @ np.array([[c, s], [-s, c]]) + pose[:2]


def fit_scan(points, target, guess):
    tree = cKDTree(target)
    best = None
    for offset in (0, -.08, .08):
        pose = np.array(guess, dtype=float).copy()
        pose[2] += offset
        for _ in range(25):
            moved = transform(points, pose)
            distances, indices = tree.query(moved)
            matched = distances < .4
            if matched.sum() < 45:
                break
            cutoff = min(.3, max(.035, np.quantile(distances[matched], .85)))
            matched &= distances <= cutoff
            a, b = moved[matched], target[indices[matched]]
            centre_a, centre_b = a.mean(axis=0), b.mean(axis=0)
            u, _, vt = np.linalg.svd((a - centre_a).T @ (b - centre_b))
            rot = vt.T @ u.T
            if np.linalg.det(rot) < 0:
                vt[-1] *= -1
                rot = vt.T @ u.T
            delta = centre_b - rot @ centre_a
            da = math.atan2(rot[1, 0], rot[0, 0])
            pose[:2] = rot @ pose[:2] + delta
            pose[2] += da
            if np.linalg.norm(delta) < .0005 and abs(da) < .0005:
                break
        distances, _ = tree.query(transform(points, pose))
        inliers = distances < .15
        fraction = float(inliers.mean())
        rmse = float(np.sqrt(np.mean(distances[inliers] ** 2))) if inliers.any() else 9.0
        score = rmse + .25 * (1 - fraction)
        if best is None or score < best[0]:
            best = (score, pose, fraction, rmse)
    return best[1:]


class RoomMapper:
    resolution = .06

    def __init__(self, forward=0, clockwise=True):
        self.forward, self.clockwise = forward, clockwise
        self.pose = np.zeros(3)
        self.submaps = deque(maxlen=18)
        self.cells = {}
        self.path = []
        self.environment = []
        self.latest_points = []
        self.last_record = None
        self.placed = self.rejected = 0
        self.status = 'waiting'
        self.reason = 'Waiting for a complete scan'
        self.fitness = self.rmse = None
        self.last_environment_key = None

    def add(self, scan_id, record):
        points = scan_points(record, self.forward, self.clockwise)
        self.latest_points = points.tolist()
        if len(points) < 60:
            return self.reject('Too few valid distances to estimate movement')
        # An outage with all SD scans recovered has no sensor-time gap.
        if self.last_record is not None:
            elapsed = (record['start_ms'] - self.last_record['start_ms']) & 0xffffffff
            if record['boot_id'] != self.last_record['boot_id'] or elapsed > 3000:
                return self.reject('Scan gap or rover restart: start a new room to set a new origin')
        if self.submaps:
            target = np.concatenate(self.submaps)
            _, unique = np.unique(np.floor(target / .04).astype(int), axis=0, return_index=True)
            target = target[unique]
            pose, fitness, rmse = fit_scan(points, target, self.pose)
            self.fitness, self.rmse = fitness, rmse
            step = np.linalg.norm(pose[:2] - self.pose[:2])
            turn = abs(math.atan2(math.sin(pose[2] - self.pose[2]), math.cos(pose[2] - self.pose[2])))
            if fitness < .6 or rmse > .085 or step > .55 or turn > .45:
                return self.reject('Scan match uncertain; move slowly or return to the last tracked position')
            self.pose = pose
        else:
            self.fitness, self.rmse = 1.0, 0.0
        world = transform(points, self.pose)
        self.submaps.append(world)
        self.last_record = record
        self.placed += 1
        self.status, self.reason = 'tracking', 'Incremental LiDAR estimate · no loop closure'
        self.path.append([*self.pose.tolist(), scan_id])
        self.rasterize(world)
        age = record.get('environment_age_ms')
        # DHT repeats across scans: assign each reading once, close to its acquisition.
        sample_key = (record['boot_id'], (record['end_ms'] - age) & 0xffffffff) if age is not None else None
        if age is not None and 0 <= age <= 3000 and sample_key != self.last_environment_key:
            t, h = record.get('temperature_c'), record.get('humidity_percent')
            if t is not None or h is not None:
                self.environment.append([float(self.pose[0]), float(self.pose[1]), t, h, scan_id, age])
                self.last_environment_key = sample_key
        return self.pose.tolist()

    def reject(self, reason):
        self.rejected += 1
        self.status, self.reason = 'uncertain', reason
        return None

    def rasterize(self, world):
        origin = self.pose[:2] / self.resolution
        for endpoint in world / self.resolution:
            steps = max(1, int(np.max(np.abs(endpoint - origin))))
            ray = np.floor(np.linspace(origin, endpoint, steps + 1)).astype(int)
            for x, y in ray[:-1]:
                key = (int(x), int(y))
                self.cells[key] = max(-8, self.cells.get(key, 0) - .35)
            key = tuple(map(int, ray[-1]))
            self.cells[key] = min(8, self.cells.get(key, 0) + 1.2)

    def snapshot(self):
        # One cell is one 6 cm square; unknown space is omitted.
        return dict(resolution=self.resolution, cells=[[x, y, round(v, 1)] for (x, y), v in self.cells.items()],
                    path=self.path, environment=self.environment, pose=self.pose.tolist(),
                    points=self.latest_points, placed=self.placed, rejected=self.rejected,
                    tracking=self.status, reason=self.reason, fitness=self.fitness, rmse=self.rmse)
