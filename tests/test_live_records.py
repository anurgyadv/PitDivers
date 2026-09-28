import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mapping'))
from records import Batch, ScanStore


class LiveRecordsTest(unittest.TestCase):
    def test_live_insert_preserves_sd_cursor_and_deduplicates(self):
        record = dict(boot_id=4, seq=8, start_ms=100, end_ms=300,
                      scan_time_ms=200, ranges_mm=[1000]*360)
        with tempfile.TemporaryDirectory() as folder:
            store = ScanStore(Path(folder)/'scans.db')
            store.ingest(Batch((), 12345))
            first = store.insert_live(record)
            self.assertEqual(first, store.insert_live(record))
            self.assertEqual(store.offset(), 12345)
            scan_id, saved = store.next_scan(0, boot_id=4)
            self.assertEqual(scan_id, first)
            self.assertEqual(saved['ranges_mm'][0], 1000)
            store.close()


if __name__ == '__main__':
    unittest.main()
