import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mapping'))
from autonav_core import Grid


class NearbyStartTests(unittest.TestCase):
    def test_connects_small_clear_offset_to_route(self):
        cells = {(x, y): -8 for x in range(-8, 9) for y in range(-8, 9)}
        cells[(-5, 0)] = 8
        grid = Grid(cells, .05)
        start = (-.025, .025)
        goal = (.125, .125)
        route = grid.plan_from_nearby(start, goal, clearance_m=.23,
                                      start_clearance_m=.18, tolerance_m=.10)
        self.assertTrue(route)
        self.assertTrue(grid.is_free(*route[0], .23))

    def test_rejects_unobserved_start(self):
        grid = Grid({(x, y): -8 for x in range(1, 8) for y in range(1, 8)}, .05)
        with self.assertRaisesRegex(ValueError, 'not in observed free space'):
            grid.plan_from_nearby((0, 0), (.2, .2), .1)

    def test_rejects_distant_route(self):
        cells = {(x, y): -8 for x in range(-5, 11) for y in range(-5, 11)}
        cells[(-5, 0)] = 8
        grid = Grid(cells, .05)
        with self.assertRaises(ValueError):
            grid.plan_from_nearby((-.025, .025), (.25, .25),
                                  clearance_m=.23, tolerance_m=.01)


if __name__ == '__main__':
    unittest.main()
