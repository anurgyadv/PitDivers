import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mapping'))
from scan_lag import check_scan_lag


class ScanLagTest(unittest.TestCase):
    def test_current_pipeline(self):
        self.assertIsNone(check_scan_lag(500, 505, 509, 7, 7))

    def test_ros_replaying_old_scans(self):
        self.assertIn('ROS', check_scan_lag(100, 900, 904, 7, 7))

    def test_collector_behind_rover(self):
        self.assertIn('collector', check_scan_lag(500, 505, 900, 7, 7))

    def test_reboot(self):
        self.assertIn('boot', check_scan_lag(500, 505, 509, 7, 8))


if __name__ == '__main__':
    unittest.main()
