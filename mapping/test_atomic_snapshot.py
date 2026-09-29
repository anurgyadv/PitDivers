import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from atomic_snapshot import write_json_snapshot


class HeartbeatTest(unittest.TestCase):
    @patch('atomic_snapshot.time.sleep')
    def test_transient_reader_lock_retries_then_publishes(self,sleep):
        with TemporaryDirectory() as d:
            p=Path(d)/'status.json';p.write_text('{"at":1}')
            original=os.replace
            calls=[]
            def locked(a,b):
                calls.append(1)
                if len(calls)<3:raise PermissionError('Windows reader lock')
                return original(a,b)
            with patch('atomic_snapshot.os.replace',side_effect=locked):
                self.assertTrue(write_json_snapshot(p,{'at':2}))
            self.assertEqual(json.loads(p.read_text()),{'at':2})
            self.assertEqual(len(calls),3)

    @patch('atomic_snapshot.time.sleep')
    def test_exhausted_lock_keeps_old_snapshot_and_next_tick_recovers(self,sleep):
        with TemporaryDirectory() as d:
            p=Path(d)/'status.json';p.write_text('{"at":1}')
            with patch('atomic_snapshot.os.replace',side_effect=PermissionError):
                self.assertFalse(write_json_snapshot(p,{'at':2}))
            self.assertEqual(json.loads(p.read_text()),{'at':1})
            self.assertTrue(write_json_snapshot(p,{'at':3}))
            self.assertEqual(json.loads(p.read_text()),{'at':3})

    def test_locked_temporary_file_does_not_raise(self):
        with patch('atomic_snapshot.Path.write_text',side_effect=PermissionError):
            self.assertFalse(write_json_snapshot(Path('status.json'),{'at':1}))
