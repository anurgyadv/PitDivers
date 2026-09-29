import unittest
from autonav_core import Grid
from demo_planner import plan_tour

class DemoPlannerTest(unittest.TestCase):
    def setUp(self):
        self.grid = Grid({(x,y):-8 for x in range(50) for y in range(50)}, .1)

    def test_arbitrary_off_trajectory_goals_and_return(self):
        result=plan_tour(self.grid,(.55,.55),[[3.55,.55],[1.55,.55]],True,.18)
        self.assertEqual(len(result['goals']),3)
        self.assertEqual(result['goals'][-1],[.55,.55])
        self.assertAlmostEqual(result['distance_m'],6.,places=4)
        self.assertTrue(result['path'])

    def test_reject_wall_unknown_nan_and_too_many(self):
        for points in ([[0.,0.]],[[99.,99.]],[[float('nan'),1.]],[[1.,1.]]*7):
            with self.assertRaises(ValueError):plan_tour(self.grid,(.55,.55),points,True,.18)

    def test_astar_detours_wall_and_disconnected_rejected(self):
        self.grid.cells.update({(20,y):8 for y in range(35)})
        r=plan_tour(self.grid,(1.,1.),[[3.,1.]],False,.18)
        self.assertGreater(r['distance_m'],5.)
        self.grid.cells.update({(20,y):8 for y in range(50)})
        with self.assertRaises(ValueError):plan_tour(self.grid,(1.,1.),[[3.,1.]],False,.18)
