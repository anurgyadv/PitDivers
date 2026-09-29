from __future__ import annotations

import io
import math
import unittest

from webapp.vio import (
    CAMERA_PROFILES,
    normalise_imu_samples,
    read_mjpeg_part,
    rover_camera_control_url,
    rover_service_url,
)


class CameraProfileTests(unittest.TestCase):
    def test_profiles_match_esp32_camera_3_3_framesize_enum(self) -> None:
        self.assertEqual(CAMERA_PROFILES["quality"]["framesize"], 10)
        self.assertEqual(CAMERA_PROFILES["vio"]["framesize"], 6)
        self.assertEqual(CAMERA_PROFILES["vio"]["software_jpeg_quality"], 50)


class RoverServiceUrlTests(unittest.TestCase):
    def test_derives_ipv4_service_url(self) -> None:
        self.assertEqual(
            rover_service_url("http://192.168.0.69:81/stream", "imu"),
            "http://192.168.0.69:82/imu",
        )

    def test_brackets_ipv6_host(self) -> None:
        self.assertEqual(
            rover_service_url("http://[fe80::1234]:81/stream", "/sensors"),
            "http://[fe80::1234]:82/sensors",
        )

    def test_derives_camera_control_url_without_stream_port(self) -> None:
        self.assertEqual(
            rover_camera_control_url(
                "http://192.168.0.69:81/stream", "software_jpeg_quality", 60
            ),
            "http://192.168.0.69/control?var=software_jpeg_quality&val=60",
        )


class MjpegPartTests(unittest.TestCase):
    def test_preserves_frame_synchronisation_headers(self) -> None:
        jpeg = b"\xff\xd8frame\xff\xd9"
        body = (
            b"\r\n--boundary\r\n"
            b"Content-Type: image/jpeg\r\n"
            + f"Content-Length: {len(jpeg)}\r\n".encode()
            + b"X-Timestamp-Us: 1234567\r\n"
            + b"X-Boot-Id: 42\r\n"
            + b"X-Frame-Sequence: 9\r\n\r\n"
            + jpeg
        )

        part = read_mjpeg_part(io.BytesIO(body))

        self.assertIsNotNone(part)
        headers, payload = part or ({}, b"")
        self.assertEqual(payload, jpeg)
        self.assertEqual(headers["x-timestamp-us"], "1234567")
        self.assertEqual(headers["x-boot-id"], "42")
        self.assertEqual(headers["x-frame-sequence"], "9")


class ImuNormalisationTests(unittest.TestCase):
    def test_converts_raw_mpu6050_units_to_si(self) -> None:
        payload = {
            "boot_id": 77,
            "accel_lsb_per_g": 16384.0,
            "gyro_lsb_per_dps": 65.5,
            "sample_fields": [
                "sequence",
                "timestamp_us",
                "accel_x_raw",
                "accel_y_raw",
                "accel_z_raw",
                "gyro_x_raw",
                "gyro_y_raw",
                "gyro_z_raw",
                "temperature_raw",
            ],
            "samples": [[5, 2_000_000, 16384, 0, -16384, 131, 0, -131, 123]],
        }

        rows = normalise_imu_samples(payload, clock_offset_ns=500)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["boot_id"], 77)
        self.assertEqual(row["host_estimated_ns"], 2_000_000_500)
        self.assertAlmostEqual(float(row["accel_x_mps2"]), 9.80665, places=5)
        self.assertAlmostEqual(float(row["accel_z_mps2"]), -9.80665, places=5)
        self.assertAlmostEqual(float(row["gyro_x_rad_s"]), math.pi / 90, places=6)
        self.assertAlmostEqual(float(row["gyro_z_rad_s"]), -math.pi / 90, places=6)


if __name__ == "__main__":
    unittest.main()
