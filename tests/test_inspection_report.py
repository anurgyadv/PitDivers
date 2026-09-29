from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import numpy as np

from webapp import inspection_report, remote_da3
from webapp import core
from webapp import rover_control
from webapp.sensor_esp import combine


class InspectionReportTests(unittest.TestCase):
    def test_separate_sensor_esp_and_corrected_wheel_commands(self) -> None:
        readings = combine({"ok": True, "temperature_c": 22.1, "humidity_percent": 55},
                           {"ok": True, "accel_g": [0, 0, 1], "gyro_dps": [0, 1, 0], "yaw_deg": 12})
        self.assertTrue(readings["dht_ok"])
        self.assertTrue(readings["mpu_ok"])
        self.assertEqual(readings["tilt_deg"]["yaw"], 12)
        with patch.object(rover_control, "rover_request", return_value={"ok": True}) as send:
            rover_control.corrected_drive_request("http://192.168.0.99", "left", 180)
            send.assert_called_once_with("http://192.168.0.99", "/api/wheels", method="POST",
                                         params={"a": -180, "b": 180})

    def test_report_binds_saved_map_frames_and_sensor_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "data"
            capture = data / "inspection_capture"
            maps = data / "lidar-maps"
            capture.mkdir(parents=True)
            maps.mkdir()
            room_id = "faa3d8d9ed73"
            room = {"run_id": room_id, "map": {"resolution": 0.1,
                "cells": [[0, 0, 8], [1, 0, -8], [1, 1, -8]],
                "path": [[0, 0], [0.1, 0.1]],
                "environment": [[0.1, 0.1, 24.1, 51.2, 1, 100]]}}
            (maps / f"{room_id}.json").write_text(json.dumps(room), encoding="utf-8")
            for index in range(2):
                name = f"frame_{index:06d}"
                Image.new("RGB", (80, 60), "#8abed0").save(capture / f"{name}.jpg")
                (capture / f"{name}.json").write_text(json.dumps({"captured_at": "2026-09-29T00:00:00Z",
                    "sensors": {"temperature_c": 23.0, "humidity_percent": 50.0}}), encoding="utf-8")
            (capture / "sensors.jsonl").write_text(json.dumps({"captured_at": "2026-09-29T00:00:00Z",
                "sensors": {"temperature_c": 24.0, "humidity_percent": 52.0}}) + "\n", encoding="utf-8")
            with patch.object(inspection_report, "DATA_DIR", data), \
                 patch.object(inspection_report, "MAP_DIR", maps), \
                 patch.object(inspection_report, "REPORT_DIR", data / "reports"):
                result = inspection_report.build_report("inspection_capture", room_id, "Fan A", "Visual check")
            output = data / "reports" / result["id"]
            report_html = (output / "report.html").read_text(encoding="utf-8")
            self.assertIn("<model-viewer", report_html) if result["model"] else self.assertIn("DA3 model not yet available", report_html)
            self.assertIn('id="photoRange"', report_html)
            self.assertIn('id="sensorChart"', report_html)
            self.assertIn('id="downloadReview"', report_html)
            self.assertIn("All 2 recorded keyframes", report_html)
            self.assertTrue((output / "temperature.svg").is_file())
            self.assertTrue((output / "humidity.svg").is_file())
            self.assertEqual(result["sensor_samples"], 1)
            self.assertIn("24.0", result["temperature"])
            self.assertEqual(len(json.loads((output / "frames.json").read_text())), 2)
            (capture / "remote_da3.json").write_text(json.dumps({"status": {
                "model_url": "https://pc.example.ts.net/api/runs/demo/model"}}), encoding="utf-8")
            with patch.object(inspection_report, "DATA_DIR", data), \
                 patch.object(inspection_report, "REPORT_DIR", data / "reports"), \
                 patch.object(remote_da3, "remote_config", return_value={"configured": True, "url": "https://pc.example.ts.net"}), \
                 patch.object(inspection_report, "urlopen", return_value=io.BytesIO(b"glTF-example")), \
                 patch.dict("os.environ", {"PITDIVERS_REMOTE_TOKEN": "test-secret-token"}):
                updated = inspection_report.attach_remote_model(result["id"])
            self.assertEqual(updated["model_file"], "scene.glb")
            self.assertEqual((output / "scene.glb").read_bytes(), b"glTF-example")
            self.assertIn('<model-viewer src="scene.glb"', (output / "report.html").read_text(encoding="utf-8"))

    def test_remote_import_rejects_archive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("../escape.jpg", b"bad")
                output.writestr("frame_000002.jpg", b"bad")
            with patch.object(remote_da3, "DATA_DIR", data):
                with self.assertRaises(ValueError):
                    remote_da3.import_capture("test", archive.getvalue())
            self.assertFalse((data / "escape.jpg").exists())

    def test_remote_token_is_required(self) -> None:
        with patch.dict("os.environ", {"PITDIVERS_REMOTE_TOKEN": "long-private-token"}):
            with self.assertRaises(PermissionError):
                remote_da3.require_token("wrong")
            remote_da3.require_token("long-private-token")

    def test_capture_writes_video_and_sensor_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            pipeline = core.LivePipeline()
            pipeline.state = "live"
            pipeline._latest_frame = np.zeros((60, 80, 3), dtype=np.uint8)
            pipeline._frame_width = 80
            pipeline._frame_height = 60
            with patch.object(core, "DATA_DIR", Path(temp)):
                name = pipeline.start_recording("sensor_video_test", 2.0, False)
                pipeline.update_sensor_snapshot({"ok": True, "temperature_c": 23.4, "humidity_percent": 54.2})
                if pipeline._video_writer is not None:
                    pipeline._video_writer.write(pipeline._latest_frame)
                    pipeline._video_frames += 1
                manifest = pipeline.stop_recording()
            self.assertEqual(manifest["sensor_samples"], 1)
            self.assertEqual(len((Path(temp) / name / "sensors.jsonl").read_text().splitlines()), 1)
            self.assertEqual(manifest["video_file"], "video.mp4")
            self.assertGreater((Path(temp) / name / "video.mp4").stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
