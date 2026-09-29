import math
import unittest
import numpy as np
from localization_quality import MapMatcher, quality_reason, AlignmentHistory


class AlignmentHistoryTest(unittest.TestCase):
    def test_brief_gaps_preserve_progress_but_are_never_ready(self):
        h=AlignmentHistory()
        for i in range(15):
            ready=h.update(i*.3,i,None)
            self.assertFalse(h.update(i*.3+.1,i,'Waiting for fresh LiDAR',True))
        self.assertTrue(ready)
        self.assertEqual(h.count,15)
        self.assertTrue(h.update(4.5,15,None))

    def test_long_gap_and_bad_match_reset(self):
        h=AlignmentHistory()
        for i in range(16):h.update(i*.3,i,None)
        self.assertFalse(h.update(6.1,15,'Waiting for fresh LiDAR',True))
        self.assertEqual(h.count,0)
        h.update(6.2,16,None)
        h.update(6.3,17,'Live scan does not fit the saved walls')
        self.assertEqual(h.count,0)

    def test_duplicate_scan_cannot_build_confidence(self):
        h=AlignmentHistory()
        for i in range(20):self.assertFalse(h.update(i*.1,1,None))

    def test_short_uncertainty_recovery_needs_five_good_scans(self):
        h=AlignmentHistory()
        for i in range(16):h.update(i*.3,i,None)
        self.assertFalse(h.update(4.6,16,'Searching the saved map: position is still ambiguous'))
        for i in range(4):self.assertFalse(h.update(4.7+i*.3,17+i,None))
        self.assertTrue(h.update(5.9,21,None))


class LocalizationQualityTest(unittest.TestCase):
    def setUp(self):
        self.cells = [[x, y, 8 if x in (0, 39) or y in (0, 39) else -8]
                      for x in range(40) for y in range(40)]
        self.matcher = MapMatcher(self.cells, .1)
        self.points = [(1.95, y / 10 - 2.05) for y in range(4, 36)]
        self.points += [(-1.95, y / 10 - 2.05) for y in range(4, 36)]

    def test_correct_scan_matches_and_wrong_pose_does_not(self):
        good = self.matcher.score(self.points, (2., 2., 0.))
        bad = self.matcher.score(self.points, (1., 2., .6))
        self.assertGreater(good['inlier_fraction'], .9)
        self.assertLess(bad['inlier_fraction'], .5)

    def test_uncertainty_and_stale_scans_cannot_be_ready(self):
        fit = self.matcher.score(self.points, (2., 2., 0.))
        self.assertIsNone(quality_reason(fit, .05, .05, .1, .1))
        self.assertIsNotNone(quality_reason(fit, .8, .05, .1, .1))
        self.assertIsNotNone(quality_reason(fit, .05, 1., .1, .1))
        self.assertIsNotNone(quality_reason(fit, .05, .05, 1., .1))
        self.assertIsNotNone(quality_reason(fit, .05, .05, .1, 3.))

    def test_missing_and_nonfinite_data_are_rejected(self):
        fit = self.matcher.score([], (2., 2., 0.))
        self.assertIsNotNone(quality_reason(fit, .01, .01, .01, .01))
        fit = self.matcher.score(self.points, (2., 2., 0.))
        self.assertIsNotNone(quality_reason(fit, math.nan, .01, .01, .01))
        self.assertIsNotNone(quality_reason(fit, .01, .01, -.1, .01))

    def test_grid_orientation_keeps_original_coordinates(self):
        grid, origin = self.matcher.occupancy()
        self.assertEqual(origin, (0., 0.))
        self.assertEqual(grid.shape, (40, 40))
        self.assertEqual(int(grid[0, 0]), 100)
        self.assertEqual(int(grid[1, 1]), 0)


if __name__ == '__main__':
    unittest.main()
