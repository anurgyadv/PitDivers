import unittest
from autonav_core import Grid
from live_costmap import LiveCostmap


class LiveCostmapTest(unittest.TestCase):
    def test_repeated_rays_clear_stale_speck_but_keep_endpoint_wall(self):
        cells = [[x,y,-8] for x in range(-30,31) for y in range(-30,31)]
        cells += [[2,0,8],[10,0,8]]
        c = LiveCostmap(Grid.from_cells(cells,.1))
        for seq in (1,2):
            c.update((.05,.05,0),[(1.,0)],seq)
            self.assertEqual(c.grid.cells[(2,0)],8)
        c.update((.05,.05,0),[(1.,0)],3)
        self.assertEqual(c.grid.cells[(2,0)],-8)
        self.assertEqual(c.grid.cells[(10,0)],8)

    def test_unknown_space_and_duplicate_scans_do_not_become_clear(self):
        c=LiveCostmap(Grid.from_cells([[0,0,-8],[2,0,8],[10,0,8]],.1))
        for _ in range(4): c.update((.05,.05,0),[(1.,0)],1)
        self.assertEqual(c.grid.cells[(2,0)],8)
        self.assertNotIn((5,0),c.grid.cells)

    def test_current_obstacle_overrides_previously_clear_map(self):
        c=LiveCostmap(Grid.from_cells([[x,0,-8] for x in range(20)],.1))
        c.update((.05,.05,0),[(.5,0)],1)
        self.assertEqual(c.grid.cells[(5,0)],8)
        c.reset()
        self.assertEqual(c.grid.cells[(5,0)],-8)


if __name__ == '__main__': unittest.main()
