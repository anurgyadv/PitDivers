"""Map/scan agreement independent of ROS transform freshness."""
from __future__ import annotations
import math
import numpy as np
from scipy.ndimage import distance_transform_edt


class AlignmentHistory:
    """Keep scan agreement across short transport gaps, never report stale ready."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.count = 0
        self.since = self.last_good = self.stamp = None
        self.trusted_at = None

    def update(self, now, stamp, reason, transport_gap=False):
        trusted=self.trusted_at
        if self.last_good is not None and now-self.last_good > 1.5:
            self.reset()
            trusted=None
        if reason:
            if not transport_gap:
                self.reset()
                if reason in ('Searching the saved map: position is still ambiguous',
                              'Waiting for an AMCL pose update') and trusted is not None and now-trusted<=3:
                    self.trusted_at=trusted
            return False
        if stamp is None:
            self.reset()
            return False
        if stamp != self.stamp:
            self.count += 1
            if self.since is None:
                self.since = now
            self.last_good = now
            self.stamp = stamp
        quick=self.trusted_at is not None and now-self.trusted_at<=3
        ready=self.count >= (5 if quick else 15) and now-self.since >= (1. if quick else 3.)
        if ready:self.trusted_at=now
        return ready


class MapMatcher:
    def __init__(self, cells, resolution):
        self.resolution = float(resolution)
        a = np.asarray(cells, dtype=int)
        self.minimum = a[:, :2].min(axis=0)
        maximum = a[:, :2].max(axis=0)
        self.grid = np.full(tuple((maximum - self.minimum + 1)[::-1]), -1, dtype=np.int8)
        xy = a[:, :2] - self.minimum
        self.grid[xy[:, 1], xy[:, 0]] = np.where(a[:, 2] == 8, 100,
                                                         np.where(a[:, 2] == -8, 0, -1))
        self.distance = distance_transform_edt(self.grid != 100) * self.resolution

    def occupancy(self):
        return self.grid, tuple(self.minimum * self.resolution)

    def score(self, points, pose):
        points = np.asarray(points, dtype=float).reshape(-1, 2)
        points = points[np.isfinite(points).all(axis=1)]
        if not len(points) or not all(map(math.isfinite, pose)):
            return dict(beams=0, inlier_fraction=0., median_error_m=None)
        x, y, yaw = pose
        c, s = math.cos(yaw), math.sin(yaw)
        world = points @ np.array([[c, s], [-s, c]]) + [x, y]
        cells = np.floor(world / self.resolution).astype(int) - self.minimum
        valid = ((cells >= 0).all(axis=1) & (cells[:, 0] < self.grid.shape[1])
                 & (cells[:, 1] < self.grid.shape[0]))
        distances = np.full(len(points), 6.)
        selected = cells[valid]
        distances[valid] = self.distance[selected[:, 1], selected[:, 0]]
        return dict(beams=len(points), inlier_fraction=float(np.mean(distances <= .15)),
                    median_error_m=float(np.median(distances)))


def quality_reason(fit, xy_std, yaw_std, scan_age, pose_age):
    if not all(math.isfinite(v) and v >= 0 for v in (xy_std, yaw_std, scan_age, pose_age)):
        return 'Invalid localization measurement'
    if scan_age > .6:
        return 'Waiting for fresh LiDAR'
    if pose_age > 2.:
        return 'Waiting for an AMCL pose update'
    if fit['beams'] < 50:
        return 'Too few valid LiDAR returns to locate the rover'
    if xy_std > .20 or yaw_std > math.radians(15):
        return 'Searching the saved map: position is still ambiguous'
    if fit['inlier_fraction'] < .60 or fit['median_error_m'] is None or fit['median_error_m'] > .12:
        return 'Live scan does not fit the saved walls'
    return None
