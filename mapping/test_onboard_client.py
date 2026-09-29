import math
import unittest
from unittest.mock import patch,MagicMock
from onboard_motion import OnboardClient

class Tests(unittest.TestCase):
    def test_scan_orientation(self):
        self.assertEqual(OnboardClient('http://rover',2.936).front,192)
    def test_no_network_on_invalid_command(self):
        c=OnboardClient('http://rover',0)
        with patch.object(c,'request') as req:
            for angle in (float('nan'),181,0):
                with self.assertRaises(ValueError):c.turn(angle)
            with self.assertRaises(ValueError):c.hold(45,180)
            req.assert_not_called()
    def test_turn_heartbeat_reuses_id_and_propagates_fault(self):
        c=OnboardClient('http://rover',0);c.turn_id=42
        import time
        c.started=time.monotonic()
        with patch.object(c,'request',return_value={'id':42,'mode':'fault','control_age_ms':0,'reason':'obstacle'}) as req:
            with self.assertRaisesRegex(OSError,'obstacle'):c.poll_turn()
            self.assertEqual(req.call_args.args,('/api/motion/heartbeat',{'id':42}))
    def test_hold_sends_small_target(self):
        c=OnboardClient('http://rover',2.936)
        with patch.object(c,'request',return_value={'queued':True}) as req:
            c.hold(12,180)
            p=req.call_args.args[1]
            self.assertEqual((p['kind'],p['angle'],p['duty'],p['front']),('hold',12,180,192))
    @patch('onboard_motion.urlopen')
    def test_turn_sent_once_then_only_heartbeat(self,http):
        c=OnboardClient('http://rover',0)
        with patch.object(c,'status',return_value={'mode':'idle','ready':True}),patch.object(c,'request') as req:
            req.side_effect=lambda path,args: {'id':args['id'],'mode':'turn','control_age_ms':0}
            c.turn(90);c.poll_turn();c.poll_turn()
            self.assertEqual([v.args[0] for v in req.call_args_list],['/api/motion','/api/motion/heartbeat','/api/motion/heartbeat'])

if __name__=='__main__':unittest.main()
