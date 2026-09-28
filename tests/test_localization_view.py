import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mapping'))

from localization_view import make_localization_view


class LocalizationViewTests(unittest.TestCase):
    def setUp(self):
        self.saved = {
            'run_id': 'c3c666243fd2', 'created': 10,
            'map': {'resolution': .05, 'cells': [[1, 2, -8]],
                    'path': [[0, 0, 0, 1]], 'environment': [],
                    'pose': [0, 0, 0], 'points': [], 'placed': 1,
                    'rejected': 0, 'fitness': None, 'rmse': None},
        }
        self.live = {
            'saved_at': 100, 'last_id': 55,
            'map': {'cells': [[9, 9, 8]], 'path': [[.4, .2, 0, 55]],
                    'environment': [[.4, .2, 21.2, 55.0, 55, 0]],
                    'pose': [.4, .2, 0], 'points': [[1, 0]],
                    'tracking': 'tracking'},
        }

    def test_live_pose_overlays_saved_geometry_without_expanding_it(self):
        view = make_localization_view(self.saved, self.live, {'scan_age_s': .1, 'pose_age_s': .1})
        self.assertEqual(view['run_id'], 'c3c666243fd2')
        self.assertEqual(view['map']['cells'], [[1, 2, -8]])
        self.assertEqual(view['map']['pose'], [.4, .2, 0])
        self.assertEqual(view['map']['live_path'], [[.4, .2, 0, 55]])
        self.assertEqual(view['map']['tracking'], 'tracking')

    def test_stale_scan_marks_last_known_pose_as_offline(self):
        view = make_localization_view(self.saved, self.live, {'scan_age_s': 35, 'pose_age_s': 35})
        self.assertEqual(view['map']['pose'], [.4, .2, 0])
        self.assertEqual(view['map']['tracking'], 'offline')
        self.assertIn('last known', view['map']['reason'])

    def test_replayed_scans_are_not_claimed_as_a_live_pose(self):
        mission = {'scan_age_s': .1, 'pose_age_s': .1}
        network = {'connected': True, 'last_seen': 99, 'scan_received_at': 99,
                   'lidar': {'running': True}}
        view = make_localization_view(self.saved, self.live, mission,
                                      network=network, pending=60, now=100)
        self.assertEqual(view['map']['tracking'], 'waiting')
        self.assertIn('recorded scans', view['map']['reason'])

        network['connected'] = False
        view = make_localization_view(self.saved, self.live, mission,
                                      network=network, pending=0, now=100)
        self.assertEqual(view['map']['tracking'], 'offline')


if __name__ == '__main__':
    unittest.main()
