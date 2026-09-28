"""Dashboard mission command and stale-status checks."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from autonav_io import read_status, write_command


class MissionIoTest(unittest.TestCase):
    def test_fresh_status_and_atomic_command(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(read_status(root)['state'], 'offline')
            (root/'status.json').write_text(json.dumps({'at': time.time()-5, 'state': 'active'}))
            self.assertEqual(read_status(root)['state'], 'offline')
            (root/'status.json').write_text(json.dumps({'at': time.time(), 'state': 'idle'}))
            self.assertEqual(read_status(root)['state'], 'idle')
            first = write_command(root, 'start', 'c3c666243fd2', round_trip=True)
            self.assertTrue(first['round_trip'])
            second = write_command(root, 'cancel', 'c3c666243fd2')
            self.assertNotEqual(first['nonce'], second['nonce'])
            self.assertEqual(json.loads((root/'command.json').read_text())['action'], 'cancel')


if __name__ == '__main__':
    unittest.main()
