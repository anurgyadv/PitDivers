"""ROS orchestration tests with all hardware I/O mocked."""
import threading
import time
import unittest
from unittest.mock import MagicMock
try:
    from autonav_ros import HallwayNavigator
except ImportError:
    HallwayNavigator=None

@unittest.skipIf(HallwayNavigator is None,'ROS runtime required')
class Tests(unittest.TestCase):
    def node(self):
        n=MagicMock();now=time.monotonic()
        n.command_file.exists.return_value=False;n.state='active'
        n.last_tick=now;n.last_scan=now;n.control_lock=threading.Lock()
        n.onboard_turn=False;n.onboard_poll_at=0.;n.turn_completed_at=0.
        n.last_status=0.;n.last_wheel_command=0.;n.pause_until=0.
        n.turn_started=None;n.turn_progress=None
        n.pose.return_value=((1.,1.,0.),.01);n.scan_pipeline_reason.return_value=None
        n.steering_yaw.return_value=0.;n.clearance_m=.23
        n.forward_offset=0.;n.reverse=False;n.goal=(3.,3.);n.sweep_clearance=2.
        n.nearest_front=n.nearest_rear=2.;n.progress_pose=(1.,1.);n.progress_at=now
        n.grid.is_free.return_value=True
        return n
    def test_local_turn_does_not_wait_for_ros_pose(self):
        n=self.node();n.onboard_turn=True
        n.local_motion.poll_turn.return_value={'mode':'turn','reason':'ESP gyro turn'}
        HallwayNavigator.tick(n)
        n.pose.assert_not_called();n.send_wheels.assert_not_called()
        n.local_motion.poll_turn.assert_called_once()
    def test_local_fault_stops_mission(self):
        n=self.node();n.onboard_turn=True;n.local_motion.poll_turn.side_effect=OSError('obstacle')
        HallwayNavigator.tick(n);n.pause.assert_called_once()
        self.assertIn('obstacle',n.pause.call_args.args[0])
    def test_new_turn_is_delegated_once(self):
        n=self.node();n.target.return_value=(1.,3.)
        HallwayNavigator.tick(n)
        n.local_motion.turn.assert_called_once_with(90.)
        self.assertTrue(n.onboard_turn);n.send_wheels.assert_not_called()
    def test_straight_travel_uses_heading_target(self):
        n=self.node();n.target.return_value=(3.,1.)
        HallwayNavigator.tick(n)
        n.local_motion.hold.assert_called_once_with(0.,200)
        n.send_wheels.assert_not_called()
    def test_done_requires_new_localization_before_translation(self):
        n=self.node();n.onboard_turn=True;n.local_motion.poll_turn.return_value={'mode':'done'}
        HallwayNavigator.tick(n)
        self.assertFalse(n.onboard_turn);self.assertGreater(n.turn_completed_at,0)
        n.local_motion.hold.assert_not_called()
        n.last_tick=time.monotonic();HallwayNavigator.tick(n)
        n.local_motion.hold.assert_not_called()

if __name__=='__main__':unittest.main()
