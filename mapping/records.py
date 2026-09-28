"""Durable ingestion of PitDivers microSD scan records, independent of ROS."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen


@dataclass(frozen=True)
class Batch:
    lines: tuple[str, ...]
    next_offset: int


def validate_record(record: object) -> dict:
    if not isinstance(record, dict):
        raise ValueError("record is not an object")
    ranges = record.get("ranges_mm")
    if not isinstance(ranges, list) or len(ranges) != 360:
        raise ValueError("record needs 360 LiDAR ranges")
    if not all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 65535 for v in ranges):
        raise ValueError("invalid LiDAR range")
    for key in ("boot_id", "seq", "start_ms", "end_ms", "scan_time_ms"):
        if not isinstance(record.get(key), int):
            raise ValueError(f"missing or invalid {key}")
    return record


def fetch_batch(base_url: str, offset: int, timeout: float = 3.0) -> Batch:
    url = f"{base_url.rstrip('/')}/api/records?offset={offset}"
    with urlopen(url, timeout=timeout) as response:
        header = response.headers.get("X-Next-Offset")
        if header is None:
            raise ValueError("rover did not return X-Next-Offset")
        next_offset = int(header)
        body = response.read().decode("utf-8")
    if next_offset < offset:
        raise ValueError("rover returned a backward log offset")
    return Batch(tuple(body.splitlines()), next_offset)


class ScanStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY,
                boot_id INTEGER NOT NULL,
                seq INTEGER NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                record_json TEXT NOT NULL,
                map_x_m REAL,
                map_y_m REAL,
                map_yaw_rad REAL,
                UNIQUE (boot_id, seq)
            );
        """)

    def close(self) -> None:
        self.db.close()

    def offset(self) -> int:
        row = self.db.execute("SELECT value FROM meta WHERE key='sd_offset'").fetchone()
        return int(row[0]) if row else 0

    def ingest(self, batch: Batch) -> tuple[int, int]:
        """Insert valid records and the cursor in one transaction.

        A torn JSON line left by a power failure is skipped; the next intact
        line remains usable. Returns (inserted, invalid).
        """
        inserted = invalid = 0
        with self.db:
            for line in batch.lines:
                try:
                    record = validate_record(json.loads(line))
                except (ValueError, json.JSONDecodeError):
                    invalid += 1
                    continue
                cursor = self.db.execute(
                    "INSERT OR IGNORE INTO scans "
                    "(boot_id,seq,start_ms,end_ms,record_json) VALUES (?,?,?,?,?)",
                    (record["boot_id"], record["seq"], record["start_ms"],
                     record["end_ms"], line),
                )
                inserted += cursor.rowcount
            self.db.execute(
                "INSERT INTO meta(key,value) VALUES('sd_offset',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(batch.next_offset),),
            )
        return inserted, invalid

    def next_scan(self, after_id: int, boot_id: int | None = None) -> tuple[int, dict] | None:
        if boot_id is None:
            row = self.db.execute(
                "SELECT id, record_json FROM scans WHERE id>? ORDER BY id LIMIT 1", (after_id,)
            ).fetchone()
        else:
            row = self.db.execute(
                "SELECT id, record_json FROM scans WHERE id>? AND boot_id=? ORDER BY id LIMIT 1",
                (after_id, boot_id),
            ).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def insert_live(self, record: dict) -> int:
        """Store a current scan without moving the microSD download cursor."""
        record = validate_record(record)
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO scans "
                "(boot_id,seq,start_ms,end_ms,record_json) VALUES (?,?,?,?,?)",
                (record['boot_id'], record['seq'], record['start_ms'],
                 record['end_ms'], json.dumps(record)),
            )
            row = self.db.execute(
                'SELECT id FROM scans WHERE boot_id=? AND seq=?',
                (record['boot_id'], record['seq']),
            ).fetchone()
        return row[0]

    def set_pose(self, scan_id: int, x: float, y: float, yaw: float) -> None:
        with self.db:
            self.db.execute(
                "UPDATE scans SET map_x_m=?,map_y_m=?,map_yaw_rad=? WHERE id=?",
                (x, y, yaw, scan_id),
            )

    def placed_environment(self) -> list[tuple[float, float, float | None, float | None]]:
        rows = self.db.execute(
            "SELECT map_x_m,map_y_m,record_json FROM scans "
            "WHERE map_x_m IS NOT NULL AND map_y_m IS NOT NULL ORDER BY id"
        )
        return [(x, y, (r := json.loads(raw)).get("temperature_c"),
                 r.get("humidity_percent")) for x, y, raw in rows]
