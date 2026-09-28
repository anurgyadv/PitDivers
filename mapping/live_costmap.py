"""Reconcile saved occupied cells with repeated, confidently placed live rays."""
import math
from autonav_core import Grid


class LiveCostmap:
    def __init__(self, base: Grid, radius=2.):
        self.base, self.radius = base, radius
        self.reset()

    def reset(self):
        self.grid = Grid(dict(self.base.cells), self.base.resolution)
        self.clear_votes = {}
        self.last_key = None

    def update(self, pose, points, scan_key):
        if scan_key == self.last_key:
            return self.grid
        self.last_key = scan_key
        x,y,yaw = pose
        c,s = math.cos(yaw), math.sin(yaw)
        clear, hits = set(), set()
        for px,py in points:
            distance = math.hypot(px,py)
            if not math.isfinite(distance) or not .08 <= distance < 5.95:
                continue
            dx,dy = c*px-s*py, s*px+c*py
            if distance <= self.radius:
                hits.add(self.base.cell((x+dx,y+dy)))
            reach = min(self.radius, max(0.,distance-.10))
            steps = max(1, math.ceil(reach/(self.base.resolution/3)))
            for i in range(steps+1):
                ratio = reach/distance*i/steps
                cell = self.base.cell((x+dx*ratio,y+dy*ratio))
                if cell in self.base.cells:
                    clear.add(cell)
        # Endpoints always win over a crossing ray. Unknown map space stays blocked.
        for cell in clear-hits:
            self.clear_votes[cell] = min(3,self.clear_votes.get(cell,0)+1)
            if self.clear_votes[cell] >= 3 and self.base.cells.get(cell) in (-8,8):
                self.grid.cells[cell] = -8
        for cell in hits:
            self.clear_votes[cell] = 0
            self.grid.cells[cell] = 8
        return self.grid
