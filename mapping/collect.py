"""Copy the rover's append-only microSD scan log into a local SQLite database."""

from __future__ import annotations

import argparse
import time

from records import ScanStore, fetch_batch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rover", default="http://192.168.0.99")
    parser.add_argument("--db", default="mapping/room_scans.sqlite3")
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    store = ScanStore(args.db)
    print(f"Collecting {args.rover} into {args.db}; Ctrl+C to stop", flush=True)
    try:
        while True:
            try:
                old_offset = store.offset()
                batch = fetch_batch(args.rover, old_offset)
                added, invalid = store.ingest(batch)
                if added or invalid:
                    print(f"+{added} scans, {invalid} damaged lines; SD offset {batch.next_offset}", flush=True)
                if batch.next_offset == old_offset:
                    time.sleep(args.interval)
            except (OSError, ValueError) as exc:
                print(f"Waiting for rover: {exc}", flush=True)
                time.sleep(3)
    except KeyboardInterrupt:
        pass
    finally:
        store.close()


if __name__ == "__main__":
    main()
