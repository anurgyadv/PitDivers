"""Run in sourced ROS WSL; motor HTTP is mocked, no hardware moves."""
import unittest
import time
from unittest.mock import patch,MagicMock
try:
    from autonav_ros import HallwayNavigator
except ImportError:
    HallwayNavigator=None
from autonav_core import Grid

@unittest.skipIf(HallwayNavigator is None,'ROS runtime required')
class SequenceTest(unittest.TestCase):
    @patch('autonav_ros.urlopen')
    @patch('autonav_ros.json.load', return_value={'signed_wheels':True,'lease_ms':600})
    def test_forward_demo_return_does_not_require_clear_rear(self,read,http):
        n=self.node(); n.state='idle'; n.run_id='test'; n.map_seen=True
        n.pose.return_value=((1.,1.,0.),.01);n.last_scan=time.monotonic()
        n.nearest_front=1.; n.nearest_rear=.34
        n.scan_pipeline_reason.return_value=None
        HallwayNavigator.start(n,{'at':time.time(),'map_id':'test','round_trip':True,'targets':[[2.,2.]]})
        self.assertEqual(n.state,'active')
        self.assertEqual(n.remaining_goals,[[1.,1.]])
        self.assertFalse(n.reverse)
        self.assertFalse(n.round_trip)

    def test_legacy_reverse_return_still_requires_clear_rear(self):
        n=self.node();n.state='idle';n.run_id='test';n.map_seen=True
        n.routes.get.return_value={'localization_destination':{'x_m':2.,'y_m':2.}}
        n.pose.return_value=((1.,1.,0.),.01);n.last_scan=time.monotonic()
        n.nearest_front=1.;n.nearest_rear=.34
        with self.assertRaisesRegex(ValueError,'rear sector'):
            HallwayNavigator.start(n,{'at':time.time(),'map_id':'test','round_trip':True})
    def node(self):
        n=MagicMock()
        n.grid=Grid({(x,y):-8 for x in range(60) for y in range(60)},.1)
        n.clearance_m=.23;n.visited=0;n.total_stops=2
        n.remaining_goals=[[3.,3.],[1.,1.]]
        return n
    @patch('autonav_ros.urlopen')
    def test_next_stop_then_return_then_stopped(self,http):
        n=self.node()
        HallwayNavigator.advance_stop(n,(2.,2.,0.),10.)
        self.assertEqual(n.goal,[3.,3.]);self.assertEqual(n.remaining_goals,[[1.,1.]])
        self.assertEqual(n.progress_at,10.5)
        HallwayNavigator.advance_stop(n,(3.,3.,0.),20.)
        self.assertEqual(n.goal,[1.,1.]);self.assertEqual(n.remaining_goals,[])
        HallwayNavigator.advance_stop(n,(1.,1.,0.),30.)
        n.stop.assert_called_once_with('arrived','Tour complete; rover stopped')
        self.assertEqual(http.call_count,3)
