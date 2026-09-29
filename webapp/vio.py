from __future__ import annotations

import math
from typing import Any, BinaryIO
from urllib.parse import urlencode, urlparse


STANDARD_GRAVITY_MPS2 = 9.80665
CAMERA_PROFILES = {
    # esp32-camera 3.3.x framesize_t values. Keep these in sync with sensor.h;
    # this release inserted 128x128 and 320x320 entries into the enum.
    "quality": {"framesize": 10, "software_jpeg_quality": 70},  # VGA, 640x480
    "vio": {"framesize": 6, "software_jpeg_quality": 50},  # QVGA, 320x240
}
IMU_CSV_FIELDS = (
    "boot_id",
    "sequence",
    "timestamp_us",
    "host_estimated_ns",
    "accel_x_raw",
    "accel_y_raw",
    "accel_z_raw",
    "gyro_x_raw",
    "gyro_y_raw",
    "gyro_z_raw",
    "temperature_raw",
    "accel_x_mps2",
    "accel_y_mps2",
    "accel_z_mps2",
    "gyro_x_rad_s",
    "gyro_y_rad_s",
    "gyro_z_rad_s",
)


def rover_service_url(stream_url: str, path: str) -> str:
    """Return a port-82 rover endpoint derived from the camera stream URL."""
    parsed = urlparse(stream_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Invalid rover camera URL")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"{parsed.scheme}://{host}:82/{path.lstrip('/')}"


def rover_camera_control_url(stream_url: str, variable: str, value: int) -> str:
    """Return a port-80 camera-control URL for an ESP32 MJPEG stream."""
    parsed = urlparse(stream_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Invalid rover camera URL")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    query = urlencode({"var": variable, "val": value})
    return f"{parsed.scheme}://{host}/control?{query}"


def read_mjpeg_part(stream: BinaryIO) -> tuple[dict[str, str], bytes] | None:
    """Read one multipart JPEG while preserving the ESP frame headers."""
    while True:
        line = stream.readline()
        if not line:
            return None
        if line.strip().startswith(b"--"):
            break

    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        name, separator, value = line.decode("latin-1").partition(":")
        if separator:
            headers[name.strip().lower()] = value.strip()

    try:
        remaining = int(headers["content-length"])
    except (KeyError, ValueError) as exc:
        raise ValueError("MJPEG frame is missing a valid Content-Length header") from exc

    chunks = bytearray()
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError("MJPEG stream ended inside a frame")
        chunks.extend(chunk)
        remaining -= len(chunk)
    return headers, bytes(chunks)


def normalise_imu_samples(
    payload: dict[str, Any], clock_offset_ns: int
) -> list[dict[str, int | float]]:
    """Convert compact ESP samples to standard SI units for VIO datasets."""
    fields = payload.get("sample_fields")
    samples = payload.get("samples")
    if not isinstance(fields, list) or not isinstance(samples, list):
        return []
    accel_scale = float(payload.get("accel_lsb_per_g") or 16384.0)
    gyro_scale = float(payload.get("gyro_lsb_per_dps") or 65.5)
    boot_id = int(payload.get("boot_id") or 0)
    result: list[dict[str, int | float]] = []
    for values in samples:
        if not isinstance(values, list) or len(values) != len(fields):
            continue
        sample = dict(zip(fields, values))
        try:
            timestamp_us = int(sample["timestamp_us"])
            accel = [int(sample[f"accel_{axis}_raw"]) for axis in "xyz"]
            gyro = [int(sample[f"gyro_{axis}_raw"]) for axis in "xyz"]
            row: dict[str, int | float] = {
                "boot_id": boot_id,
                "sequence": int(sample["sequence"]),
                "timestamp_us": timestamp_us,
                "host_estimated_ns": timestamp_us * 1000 + clock_offset_ns,
                "temperature_raw": int(sample["temperature_raw"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
        for index, axis in enumerate("xyz"):
            row[f"accel_{axis}_raw"] = accel[index]
            row[f"gyro_{axis}_raw"] = gyro[index]
            row[f"accel_{axis}_mps2"] = accel[index] / accel_scale * STANDARD_GRAVITY_MPS2
            row[f"gyro_{axis}_rad_s"] = math.radians(gyro[index] / gyro_scale)
        result.append(row)
    return result
