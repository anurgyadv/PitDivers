import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mapping'))

from atomic_snapshot import replace_with_retry


class AtomicSnapshotTests(unittest.TestCase):
    def test_transient_windows_file_lock_does_not_kill_snapshot_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'live.json'
            temp = Path(directory) / 'live.tmp'
            target.write_text('old')
            temp.write_text('new')
            from os import replace
            calls = 0

            def intermittent_replace(source, destination):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise PermissionError('file briefly held by dashboard')
                replace(source, destination)

            with patch('atomic_snapshot.os.replace', side_effect=intermittent_replace):
                replace_with_retry(temp, target)
            self.assertEqual(calls, 2)
            self.assertEqual(target.read_text(), 'new')

    def test_persistent_lock_keeps_previous_snapshot_and_allows_next_tick(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'live.json'
            temp = Path(directory) / 'live.tmp'
            target.write_text('old')
            temp.write_text('new')
            with patch('atomic_snapshot.os.replace', side_effect=PermissionError('locked')):
                self.assertFalse(replace_with_retry(temp, target, attempts=2, delay_s=0))
            self.assertEqual(target.read_text(), 'old')
            self.assertEqual(temp.read_text(), 'new')


if __name__ == '__main__':
    unittest.main()
