import json
import tempfile
import unittest
from pathlib import Path

from records import Batch, ScanStore
from render_environment import render


def sample(seq=1):
    return {"boot_id": 42, "seq": seq, "start_ms": seq * 200, "end_ms": seq * 200 + 190,
            "scan_time_ms": 190, "rpm": 300, "temperature_c": 23.5,
            "humidity_percent": 51.0, "ranges_mm": [1000] * 360}


class ScanStoreTest(unittest.TestCase):
    def test_live_boot_filter_skips_older_sd_backlog(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ScanStore(Path(folder) / 'scans.sqlite3')
            old = sample()
            current = {**sample(), 'boot_id': 99}
            store.ingest(Batch((json.dumps(old), json.dumps(current)), 200))
            self.assertEqual(store.next_scan(0, boot_id=99)[1]['boot_id'], 99)
            self.assertIsNone(store.next_scan(2, boot_id=99))
            store.close()

    def test_cursor_and_scans_survive_reopen_and_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scans.sqlite3"
            store = ScanStore(path)
            self.assertEqual(store.ingest(Batch((json.dumps(sample()),), 100)), (1, 0))
            store.close()
            store = ScanStore(path)
            self.assertEqual(store.offset(), 100)
            self.assertEqual(store.ingest(Batch((json.dumps(sample()), "damaged",
                                                 json.dumps(sample(2))), 200)), (1, 1))
            self.assertEqual(store.next_scan(0)[1]["temperature_c"], 23.5)
            store.set_pose(1, 1.2, 2.3, 0.4)
            samples = store.placed_environment()
            self.assertEqual(samples, [(1.2, 2.3, 23.5, 51.0)])
            self.assertIn("23.5", render(samples, "temperature"))
            store.close()


if __name__ == "__main__":
    unittest.main()
