import math
import unittest
from unittest.mock import Mock
from drive_profile import predict_yaw,drive_duty,route_target

class ProfileTests(unittest.TestCase):
    def test_prediction_is_bounded_and_uses_bias(self):
        imu={'gyro_dps':[0,0,92],'accel_g':[0,0,1],'age_ms':10}
        self.assertAlmostEqual(predict_yaw(0,.1,imu,.1,2),math.radians(9))
        self.assertEqual(predict_yaw(0,.3,imu,.1,2),0)
        self.assertEqual(predict_yaw(0,.1,imu,.3,2),0)
        self.assertEqual(predict_yaw(0,.1,imu,.1,None),0)
        imu['accel_g'][2]=.2
        self.assertEqual(predict_yaw(0,.1,imu,.1,2),0)

    def test_boost_only_clear_straight_far_from_goal(self):
        self.assertEqual(drive_duty(0,2,2,True),200)
        for values in [(.3,2,2,True),(0,.7,2,True),(0,2,.4,True),(0,2,2,False)]:
            self.assertEqual(drive_duty(*values),180)

    def test_lookahead_does_not_shortcut_blocked_corner(self):
        grid=Mock();path=[(0,0),(.25,0),(.5,0),(.5,.3)]
        grid.segment_free.side_effect=lambda a,b,c:b[1]==0
        self.assertEqual(route_target(path,(0,0,0),grid,.23),(.5,0))

if __name__=='__main__':unittest.main()
