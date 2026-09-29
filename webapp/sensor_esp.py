"""Normalize the wheel/sensor ESP's separate environment and IMU responses."""
from __future__ import annotations

import math


def combine(environment: dict, imu: dict | None = None) -> dict:
    imu = imu or {}
    accel = imu.get("accel_g")
    gyro = imu.get("gyro_dps")
    valid_imu = (imu.get("ok") is True and isinstance(accel, list) and len(accel) == 3
                 and isinstance(gyro, list) and len(gyro) == 3
                 and all(isinstance(value, (int, float)) and math.isfinite(value) for value in accel + gyro))
    result = dict(environment)
    result["dht_ok"] = environment.get("ok") is True
    result["mpu_ok"] = valid_imu
    result["sonar_ok"] = False
    if valid_imu:
        x, y, z = accel
        result["accel_g"] = dict(zip(("x", "y", "z"), accel))
        result["gyro_dps"] = dict(zip(("x", "y", "z"), gyro))
        result["tilt_deg"] = {
            "roll": math.degrees(math.atan2(y, z)),
            "pitch": math.degrees(math.atan2(-x, math.hypot(y, z))),
            "yaw": float(imu.get("yaw_deg") or 0),
        }
        result["mpu_temperature_c"] = None
    return result
