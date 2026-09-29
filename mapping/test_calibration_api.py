import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from demo_server import Demo

class CalibrationApiTests(unittest.TestCase):
    def test_unsupported_firmware_is_explicit(self):
        d=Demo(); d.calibration_rover='http://test'
        with patch('demo_server.urlopen',side_effect=HTTPError('x',404,'missing',{},None)):
            with self.assertRaisesRegex(ValueError,'Flash the gyro'):d.calibration()
    def test_active_mission_rejects_start_before_network(self):
        d=Demo()
        with patch('demo_server.read_status',return_value={'state':'active'}),patch('demo_server.urlopen') as network:
            with self.assertRaises(ValueError):d.calibration('start')
            network.assert_not_called()
    def test_heartbeat_posts_only_to_calibration(self):
        d=Demo(); d.calibration_rover='http://test'
        with patch('demo_server.urlopen',return_value=io.BytesIO(b'{"ok":true}')) as network:
            self.assertTrue(d.calibration('heartbeat')['ok'])
            req=network.call_args.args[0]
            self.assertEqual(req.full_url,'http://test/api/turn-calibration/heartbeat')
            self.assertEqual(req.get_method(),'POST')
            self.assertEqual(network.call_args.kwargs['timeout'],2)
    def test_other_actions_rejected(self):
        with self.assertRaises(ValueError):Demo().calibration('drive')

    def test_timeout_explains_stop_without_retry(self):
        d=Demo(); d.calibration_rover='http://test'
        with patch('demo_server.urlopen',side_effect=TimeoutError('timed out')) as network:
            with self.assertRaisesRegex(ValueError,'Press STOP'):
                d.calibration('heartbeat')
            self.assertEqual(network.call_count,1)

    def test_conflict_keeps_firmware_reason(self):
        d=Demo(); d.calibration_rover='http://test'
        error=HTTPError('x',409,'Conflict',{},io.BytesIO(b'{"error":"Need 45 cm clearance"}'))
        with patch('demo_server.urlopen',side_effect=error):
            with self.assertRaisesRegex(ValueError,'Need 45 cm clearance'):d.calibration()

if __name__=='__main__':unittest.main()
