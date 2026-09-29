import unittest
from urllib.parse import parse_qs, urlparse
from drive_commands import manual_request


class ManualDriveTest(unittest.TestCase):
    def test_calibrated_turns_use_opposite_physical_wheel_directions_at_full_duty(self):
        # Channel A is physically reversed. Demo left maps to firmware backward.
        for direction, expected in [('backward', '-255'), ('forward', '255')]:
            request = manual_request('http://rover', direction, 255)
            self.assertEqual(request.get_method(), 'POST')
            self.assertEqual(parse_qs(urlparse(request.full_url).query),
                             {'a': [expected], 'b': [expected]})

    def test_straight_and_stop_do_not_inherit_full_turn_power(self):
        request = manual_request('http://rover', 'left', 180)
        self.assertEqual(parse_qs(urlparse(request.full_url).query),
                         {'a': ['-180'], 'b': ['180']})
        self.assertEqual(manual_request('http://rover', 'stop', 255).full_url,
                         'http://rover/stop')
        self.assertEqual(manual_request('http://rover', 'left').full_url,
                         'http://rover/left')

    def test_reject_bad_duty(self):
        for duty in [True, 256, -255, 1.5, '255']:
            with self.assertRaises(ValueError):
                manual_request('http://rover', 'backward', duty)
