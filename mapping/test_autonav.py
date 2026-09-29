"""Navigation logic checks; no ROS process or real motors are used."""

import math
import unittest

from autonav_core import Grid, MotionInputs, estimate_forward_offset, motion_command, turn_command, RecoveryGate, TurnProgress


class AutonavTest(unittest.TestCase):
    def test_slow_turn_continues_with_measured_progress(self):
        turn = TurnProgress(10., 0., 1)
        # Slow physical rotation used to trip the 2-degree/1-second check.
        for i in range(1, 71):
            self.assertIsNone(turn.update(10.+i*.1, i*.002))

    def test_turn_stall_and_absolute_timeout_are_distinct(self):
        turn = TurnProgress(10., 0., 1)
        self.assertIsNone(turn.update(11.1, 0.))
        self.assertEqual(turn.update(12.1, 0.), 'Turn stalled: no measured rotation for 2 seconds')
        turn = TurnProgress(0., 0., 1)
        for i in range(1, 150):
            self.assertIsNone(turn.update(i*.1, i*.02))
        self.assertEqual(turn.update(15.1, 3.02), 'Turn exceeded 15-second limit')

    def test_turn_wraparound_and_wrong_direction(self):
        turn = TurnProgress(0., math.pi-.01, 1)
        self.assertIsNone(turn.update(.2, -math.pi+.02))
        self.assertAlmostEqual(turn.rotation, .03)
        self.assertEqual(TurnProgress(0.,0.,1).update(.2,-.06),
                         'Turn moved opposite to commanded direction')

    def test_recovery_waits_for_continuous_health_and_times_out(self):
        gate = RecoveryGate(0.)
        self.assertEqual(gate.update(1.,True),'wait')
        self.assertEqual(gate.update(1.4,True),'wait')
        self.assertEqual(gate.update(1.5,True),'resume')
        self.assertEqual(gate.update(1.6,False),'wait')
        self.assertEqual(gate.update(1.7,True),'wait')
        self.assertEqual(gate.update(2.1,True),'wait')
        self.assertEqual(gate.update(2.2,True),'resume')
        self.assertEqual(RecoveryGate(0.).update(31.,False),'timeout')

    def test_turn_requires_clear_sweep_and_fresh_data(self):
        fresh = MotionInputs((0, 0, 0), .1, .1, 2., True)
        self.assertEqual(turn_command(fresh, (0, 1), .5), (-255, -255))
        self.assertEqual(turn_command(fresh, (0, -1), .5), (255, 255))
        self.assertEqual(turn_command(fresh, (0, 1), .449), (0, 0))
        self.assertEqual(turn_command(fresh, (0, 1), .45), (-255, -255))
        self.assertEqual(turn_command(MotionInputs((0, 0, 0), .7, .1, 2., True),
                                      (0, 1), .5), (0, 0))
        self.assertEqual(turn_command(fresh, (1, 0), .5), (0, 0))

    def test_smoothing_never_cuts_through_obstacle(self):
        cells = [[x,y,-8] for x in range(9) for y in range(9)]
        cells += [[4,y,8] for y in range(7)]
        grid = Grid.from_cells(cells, .1)
        path = grid.plan((.15,.15),(.75,.15),0)
        smooth = grid.smooth(path, 0)
        self.assertTrue(all(grid.segment_free(a,b,0) for a,b in zip(smooth,smooth[1:])))
        self.assertFalse(grid.segment_free((.15,.15),(.75,.15),0))

    def test_occupancy_planner_detours_and_blocks_unknown(self):
        cells = [[x, y, -8] for x in range(7) for y in range(5)]
        cells += [[3, y, 8] for y in range(4)]
        grid = Grid.from_cells(cells, 1.0)
        path = grid.plan((0.5, 2.5), (6.5, 2.5), clearance_m=0)
        self.assertIn((3.5, 4.5), path)
        self.assertTrue(all(grid.is_free(x, y, 0) for x, y in path))
        with self.assertRaisesRegex(ValueError, 'free'):
            grid.plan((0.5, 2.5), (9.5, 2.5), clearance_m=0)

    def test_obstacle_and_stale_inputs_stop_wheels(self):
        fresh = MotionInputs(pose=(0, 0, 0), pose_age_s=.1, scan_age_s=.1,
                             nearest_front_m=2.0, wifi_ok=True)
        self.assertEqual(motion_command(fresh, (1, 0)), (-180, 180))
        for changed in [dict(pose_age_s=.7), dict(scan_age_s=.7),
                        dict(nearest_front_m=.3), dict(wifi_ok=False)]:
            sample = MotionInputs(**(fresh.__dict__ | changed))
            self.assertEqual(motion_command(sample, (1, 0)), (0, 0))

    def test_left_correction_slows_left_side_without_reversing(self):
        sample = MotionInputs(pose=(0, 0, 0), pose_age_s=.1, scan_age_s=.1,
                              nearest_front_m=2.0, wifi_ok=True)
        a, b = motion_command(sample, (1, .25))
        self.assertLess(a, 0)
        self.assertGreaterEqual(b, 0)
        self.assertLess(b, -a)
        self.assertEqual(motion_command(sample, (.03, 0)), (0, 0))

    def test_saved_trace_estimates_forward_axis_relative_to_lidar_yaw(self):
        path = [[i*.03, 0, -math.pi, i] for i in range(150)]
        offset = estimate_forward_offset(path)
        self.assertLess(abs(abs(offset) - math.pi), .05)

    def test_reverse_motion_uses_rear_heading_and_signed_wheels(self):
        sample = MotionInputs(pose=(0, 0, 0), pose_age_s=0, scan_age_s=0,
                              nearest_front_m=2, wifi_ok=True)
        self.assertEqual(motion_command(sample, (-1, 0), reverse=True), (180, -180))
        self.assertEqual(motion_command(MotionInputs((0, 0, 0), 0, 0, .3, True),
                                        (-1, 0), reverse=True), (0, 0))


if __name__ == '__main__':
    unittest.main()
