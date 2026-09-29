from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, TextIO
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import cv2
import numpy as np

from .live_semantic import LiveObjectTracker
from .low_light import LowLightProcessor
from .vio import (
    CAMERA_PROFILES,
    IMU_CSV_FIELDS,
    normalise_imu_samples,
    read_mjpeg_part,
    rover_camera_control_url,
    rover_service_url,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
RUNS_DIR = ROOT_DIR / "runs"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
LIVE_SEMANTIC_CLASSES = [
    "coffee machine", "coffee mug", "cup", "table", "chair", "door", "cabinet",
    "box", "bag", "bottle", "tool", "helmet", "electrical outlet",
    "light switch", "cable", "person",
]
MODEL_CATALOG: list[dict[str, Any]] = [
    {
        "id": "depth-anything/DA3-SMALL",
        "name": "DA3 Small",
        "parameters": "80M",
        "license": "Apache 2.0",
        "recommended": "Fastest live depth",
        "vram": "Low",
    },
    {
        "id": "depth-anything/DA3-BASE",
        "name": "DA3 Base",
        "parameters": "120M",
        "license": "Apache 2.0",
        "recommended": "Recommended for RTX 5070 live use",
        "vram": "Moderate",
    },
    {
        "id": "depth-anything/DA3-LARGE-1.1",
        "name": "DA3 Large 1.1",
        "parameters": "350M",
        "license": "CC BY-NC 4.0",
        "recommended": "Higher-quality offline reconstruction",
        "vram": "High",
    },
    {
        "id": "depth-anything/DA3-GIANT-1.1",
        "name": "DA3 Giant 1.1",
        "parameters": "1.15B",
        "license": "CC BY-NC 4.0",
        "recommended": "Experimental; likely too large for 12 GB multi-view runs",
        "vram": "Very high",
    },
    {
        "id": "depth-anything/DA3NESTED-GIANT-LARGE-1.1",
        "name": "DA3 Nested Giant/Large 1.1",
        "parameters": "1.40B",
        "license": "CC BY-NC 4.0",
        "recommended": "Research model; not recommended on this laptop",
        "vram": "Extreme",
    },
]
MODEL_IDS = {model["id"] for model in MODEL_CATALOG}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_slug(value: str, fallback: str = "capture") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip()).strip("_-")
    return (cleaned[:80] or fallback).lower()


def path_in(root: Path, name: str) -> Path:
    candidate = (root / name).resolve()
    if candidate.parent != root.resolve():
        raise ValueError("Invalid path")
    return candidate


def image_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(
        path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def folder_size(folder: Path) -> int:
    try:
        return sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())
    except OSError:
        return 0


def depth_stats(
    depth: np.ndarray, conf: np.ndarray | None, is_metric: bool
) -> dict[str, Any] | None:
    """Summarise a DA3 depth map for the live readout.

    DA3-Base is not metric, so its depth is *relative* (up to scale), not metres.
    We surface robust min/avg/max plus a relative confidence score derived from
    the model's own per-pixel confidence, and flag whether the source model
    actually produced metric depth so the UI can label the scale honestly.
    """
    finite_positive = np.isfinite(depth) & (depth > 0)
    valid = depth[finite_positive]
    if valid.size < 16:
        return None
    stats: dict[str, Any] = {
        "min": float(np.percentile(valid, 2)),
        "avg": float(valid.mean()),
        "max": float(np.percentile(valid, 98)),
        "metric": bool(is_metric),
    }
    if conf is not None and conf.shape == depth.shape:
        conf_valid = conf[finite_positive]
        conf_valid = conf_valid[np.isfinite(conf_valid)]
        if conf_valid.size:
            median = float(np.median(conf_valid))
            high = float(np.percentile(conf_valid, 95))
            # Median confidence relative to the frame's high-confidence pixels.
            # DA3 confidence is uncalibrated, so this is a relative 0–1 score.
            stats["confidence"] = max(0.0, min(1.0, median / high)) if high > 0 else 0.0
    return stats


class LivePipeline:
    """Own the ESP32 capture, live DA3 inference, and keyframe recording."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._model_lock = threading.Lock()
        self._gpu_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._inference_thread: threading.Thread | None = None
        self._sensor_thread: threading.Thread | None = None
        self._semantic_thread: threading.Thread | None = None
        self._capture: Any = None
        self._model: Any = None
        self._semantic_model: Any = None
        self._low_light = LowLightProcessor()
        self._generation = 0

        self.stream_url = "http://192.168.0.69:81/stream"
        self.sensor_base_url = "http://192.168.0.99"
        self.model_id = "depth-anything/DA3-BASE"
        self.process_res = 504
        self.inference_fps = 10.0
        self.depth_enabled = True
        self.semantic_enabled = False
        self.semantic_fps = 1.0
        self.camera_profile = "quality"
        self.rotation = 180
        self.camera_profile_error: str | None = None
        self.state = "disconnected"
        self.model_state = "idle"
        self.semantic_state = "idle"
        self.semantic_error: str | None = None
        self.error: str | None = None
        self.connected_at: str | None = None

        self._latest_frame: Any = None
        self._raw_jpeg: bytes | None = None
        self._original_jpeg: bytes | None = None
        self._depth_jpeg: bytes | None = None
        self._semantic_jpeg: bytes | None = None
        self._raw_sequence = 0
        self._depth_sequence = 0
        self._semantic_sequence = 0
        self._frame_width = 0
        self._frame_height = 0
        self._capture_fps = 0.0
        self._depth_fps = 0.0
        self._semantic_fps_actual = 0.0
        self._last_inference_ms = 0.0
        self._last_semantic_ms = 0.0
        self._depth_stats: dict[str, Any] | None = None
        self._latest_depth: Any = None
        self._latest_depth_raw_sequence = -1
        self._semantic_objects: list[dict[str, Any]] = []
        self._semantic_tracker = LiveObjectTracker()

        self._recording = False
        self._video_writer = None
        self._video_frames = 0
        self._video_error = None
        self._last_video_at = 0.0
        self._sensor_file = None
        self._sensor_samples_recorded = 0
        self._recording_name: str | None = None
        self._recording_dir: Path | None = None
        self._recording_started_at: str | None = None
        self._keyframe_fps = 2.0
        self._keyframe_count = 0
        self._last_keyframe_at = 0.0
        self._stable_only = False
        self._motion_skipped = 0
        self._telemetry_frames = 0
        self._sensor_snapshot: dict[str, Any] | None = None
        self._sensor_snapshot_received_ns = 0
        self._imu_boot_id: int | None = None
        self._imu_sequence = 0
        self._imu_rate_hz = 0
        self._imu_clock_offset_ns: int | None = None
        self._imu_clock_rtt_ns: int | None = None
        self._imu_stream_state = "idle"
        self._imu_stream_error: str | None = None
        self._imu_samples_recorded = 0
        self._imu_samples_dropped = 0
        self._imu_device_missed_total = 0
        self._imu_device_missed_at_record_start = 0
        self._imu_file: TextIO | None = None
        self._imu_writer: csv.DictWriter | None = None
        self._latest_camera_timestamp_us: int | None = None
        self._latest_camera_sequence: int | None = None
        self._latest_camera_boot_id: int | None = None

    def connect(
        self,
        stream_url: str,
        model_id: str,
        process_res: int,
        inference_fps: float,
        depth_enabled: bool = True,
        camera_profile: str = "quality",
        semantic_enabled: bool = False,
        semantic_fps: float = 1.0,
        low_light_mode: str = "off",
        low_light_strength: int = 55,
        rotation: int = 180,
        sensor_base_url: str = "http://192.168.0.99",
    ) -> None:
        self.disconnect()
        if camera_profile not in CAMERA_PROFILES:
            raise ValueError("Unknown camera profile")
        if rotation not in {0, 180}:
            raise ValueError("Camera rotation must be 0 or 180 degrees")
        with self._lock:
            self._generation += 1
            generation = self._generation
            self.stream_url = stream_url
            self.sensor_base_url = sensor_base_url.rstrip("/")
            self.model_id = model_id
            self.process_res = process_res
            self.inference_fps = inference_fps
            self.depth_enabled = depth_enabled
            self.semantic_enabled = semantic_enabled
            self.semantic_fps = semantic_fps
            self.camera_profile = camera_profile
            self.rotation = rotation
            self._low_light.configure(low_light_mode, low_light_strength)
            self._low_light.reset()
            self.camera_profile_error = None
            self.state = "connecting"
            self.model_state = "loading" if depth_enabled else "disabled"
            self.semantic_state = "loading" if semantic_enabled else "disabled"
            self.semantic_error = None
            self.error = None
            self.connected_at = utc_now()
            self._latest_frame = None
            self._raw_jpeg = None
            self._original_jpeg = None
            self._depth_jpeg = None
            self._semantic_jpeg = None
            self._raw_sequence = 0
            self._depth_sequence = 0
            self._semantic_sequence = 0
            self._capture_fps = 0.0
            self._depth_fps = 0.0
            self._semantic_fps_actual = 0.0
            self._last_inference_ms = 0.0
            self._last_semantic_ms = 0.0
            self._depth_stats = None
            self._latest_depth = None
            self._latest_depth_raw_sequence = -1
            self._semantic_objects = []
            self._semantic_tracker.reset()
            self._frame_width = 0
            self._frame_height = 0
            self._sensor_snapshot = None
            self._sensor_snapshot_received_ns = 0
            self._imu_boot_id = None
            self._imu_sequence = 0
            self._imu_rate_hz = 0
            self._imu_clock_offset_ns = None
            self._imu_clock_rtt_ns = None
            self._imu_device_missed_total = 0
            self._imu_device_missed_at_record_start = 0
            self._imu_stream_state = "connecting"
            self._imu_stream_error = None
            self._latest_camera_timestamp_us = None
            self._latest_camera_sequence = None
            self._latest_camera_boot_id = None
            self._stop_event = threading.Event()

        self._capture_thread = threading.Thread(
            target=self._capture_loop, args=(generation,), daemon=True, name="rover-capture"
        )
        self._inference_thread = (
            threading.Thread(
                target=self._inference_loop, args=(generation,), daemon=True, name="da3-live"
            )
            if depth_enabled
            else None
        )
        self._sensor_thread = threading.Thread(
            target=self._sensor_loop, args=(generation,), daemon=True, name="rover-telemetry"
        )
        self._semantic_thread = (
            threading.Thread(
                target=self._semantic_loop, args=(generation,), daemon=True, name="semantic-live"
            )
            if semantic_enabled
            else None
        )
        self._capture_thread.start()
        if self._inference_thread is not None:
            self._inference_thread.start()
        if self._semantic_thread is not None:
            self._semantic_thread.start()
        self._sensor_thread.start()

    def disconnect(self) -> None:
        self.stop_recording()
        self._stop_event.set()
        capture = self._capture
        if capture is not None:
            close = getattr(capture, "close", None)
            if callable(close):
                close()
            else:
                release = getattr(capture, "release", None)
                if callable(release):
                    release()
        for thread in (self._capture_thread, self._inference_thread, self._semantic_thread, self._sensor_thread):
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=3.0)
        with self._model_lock:
            self._model = None
            self._semantic_model = None
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
        with self._lock:
            self._generation += 1
            self._capture = None
            self._capture_thread = None
            self._inference_thread = None
            self._sensor_thread = None
            self._semantic_thread = None
            self._depth_stats = None
            self.state = "disconnected"
            self.model_state = "idle"
            self.semantic_state = "idle"
            self._imu_stream_state = "idle"
            self.connected_at = None

    def _capture_loop(self, generation: int) -> None:
        frame_counter = 0
        counter_started = time.perf_counter()
        reconnects = 0
        # The temporary camera_dashboard sketch exposes a fixed /jpg snapshot
        # endpoint and has no /control API. Its capture settings are firmware-side.
        profile_applied = urlparse(self.stream_url).path.rstrip("/").endswith("/jpg")
        while not self._stop_event.is_set() and generation == self._generation:
            if not profile_applied:
                try:
                    self._apply_camera_profile()
                    profile_applied = True
                    with self._lock:
                        self.camera_profile_error = None
                except Exception as exc:
                    with self._lock:
                        self.camera_profile_error = f"Camera profile unavailable: {exc}"
            try:
                capture = urlopen(
                    Request(
                        self.stream_url,
                        headers={"Accept": "multipart/x-mixed-replace", "Cache-Control": "no-cache"},
                    ),
                    timeout=3.0,
                )
            except Exception:
                reconnects += 1
                with self._lock:
                    self.state = "reconnecting" if reconnects > 1 else "connecting"
                    self.error = "Camera stream unavailable; retrying"
                self._stop_event.wait(1.0)
                continue

            with self._lock:
                self._capture = capture
                self.state = "live"
                self.error = None
            reconnects = 0
            content_type = capture.headers.get_content_type().lower()
            snapshot_source = content_type == "image/jpeg"
            snapshot_consumed = False

            while not self._stop_event.is_set() and generation == self._generation:
                if snapshot_source:
                    if snapshot_consumed:
                        break
                    try:
                        jpeg = capture.read(4 * 1024 * 1024)
                        headers = {key.lower(): value for key, value in capture.headers.items()}
                        part = (headers, jpeg) if jpeg else None
                    except Exception:
                        part = None
                    snapshot_consumed = True
                else:
                    try:
                        part = read_mjpeg_part(capture)
                    except Exception:
                        part = None
                if part is None:
                    with self._lock:
                        self.state = "reconnecting"
                        self.error = "Camera stream interrupted; reconnecting"
                    break
                headers, jpeg = part
                frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    continue
                if self.rotation == 180:
                    frame = cv2.rotate(frame, cv2.ROTATE_180)
                    encoded_ok, encoded = cv2.imencode(
                        ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90]
                    )
                    if encoded_ok:
                        jpeg = encoded.tobytes()
                original_jpeg = jpeg
                frame = self._low_light.process(frame)
                if self._low_light.status()["mode"] != "off":
                    encoded_ok, encoded = cv2.imencode(
                        ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88]
                    )
                    if encoded_ok:
                        jpeg = encoded.tobytes()
                now = time.perf_counter()
                received_ns = time.perf_counter_ns()
                try:
                    camera_timestamp_us = int(headers.get("x-timestamp-us", ""))
                except ValueError:
                    camera_timestamp_us = None
                try:
                    camera_sequence = int(headers.get("x-frame-sequence", ""))
                except ValueError:
                    camera_sequence = None
                try:
                    camera_boot_id = int(headers.get("x-boot-id", ""))
                except ValueError:
                    camera_boot_id = None
                frame_counter += 1
                elapsed = now - counter_started
                if elapsed >= 1.0:
                    with self._lock:
                        self._capture_fps = frame_counter / elapsed
                    frame_counter = 0
                    counter_started = now

                with self._lock:
                    self._latest_frame = frame.copy()
                    self._raw_jpeg = jpeg
                    self._original_jpeg = original_jpeg
                    self._raw_sequence += 1
                    self._latest_camera_timestamp_us = camera_timestamp_us
                    self._latest_camera_sequence = camera_sequence
                    self._latest_camera_boot_id = camera_boot_id
                    self._frame_height, self._frame_width = frame.shape[:2]
                    if self._recording and self._video_writer is not None and now - self._last_video_at >= 1 / 12:
                        try:
                            self._video_writer.write(frame)
                            self._video_frames += 1
                            self._last_video_at = now
                        except Exception as exc:
                            self._video_error = str(exc)
                    keyframe_due = (
                        self._recording
                        and self._recording_dir is not None
                        and now - self._last_keyframe_at >= 1.0 / self._keyframe_fps
                    )
                    sensor_snapshot = None
                    capture_stable = False
                    if keyframe_due and self._sensor_snapshot is not None:
                        sensor_snapshot = json.loads(json.dumps(self._sensor_snapshot))
                        capture_stable = self._sensor_is_stable(sensor_snapshot)
                    should_save = keyframe_due and (not self._stable_only or capture_stable)
                    if keyframe_due:
                        self._last_keyframe_at = now
                        if self._stable_only and not capture_stable:
                            self._motion_skipped += 1
                    record_dir = self._recording_dir
                    frame_number = self._keyframe_count
                    clock_offset_ns = self._imu_clock_offset_ns
                    imu_sequence = self._imu_sequence

                if should_save and record_dir is not None:
                    output = record_dir / f"frame_{frame_number:06d}.jpg"
                    try:
                        output.write_bytes(jpeg)
                        saved = True
                    except OSError:
                        saved = False
                    if saved:
                        estimated_device_us = (
                            camera_timestamp_us
                            if camera_timestamp_us is not None
                            else round((received_ns - clock_offset_ns) / 1000)
                            if clock_offset_ns is not None
                            else None
                        )
                        telemetry = {
                            "frame": output.name,
                            "captured_at": utc_now(),
                            "host_received_monotonic_ns": received_ns,
                            "camera_timestamp_us": estimated_device_us,
                            "camera_timestamp_source": (
                                "esp32_frame_header"
                                if camera_timestamp_us is not None
                                else "host_receive_clock_estimate"
                                if estimated_device_us is not None
                                else "unavailable"
                            ),
                            "camera_sequence": camera_sequence,
                            "camera_boot_id": camera_boot_id,
                            "latest_imu_sequence": imu_sequence,
                            "capture_stable": capture_stable,
                            "sensors": sensor_snapshot,
                        }
                        write_json(output.with_suffix(".json"), telemetry)
                        with self._lock:
                            self._keyframe_count += 1
                            if sensor_snapshot is not None:
                                self._telemetry_frames += 1

            try:
                capture.close()
            except OSError:
                pass
            with self._lock:
                if self._capture is capture:
                    self._capture = None
            # Snapshot-only camera sketches expose /jpg rather than a multipart
            # stream. Re-open that endpoint quickly to create a dashboard feed.
            self._stop_event.wait(0.04 if snapshot_source else 0.25)

    def _apply_camera_profile(self) -> None:
        settings = CAMERA_PROFILES[self.camera_profile]
        for variable, value in settings.items():
            control_url = rover_camera_control_url(self.stream_url, variable, value)
            with urlopen(Request(control_url, headers={"Accept": "*/*"}), timeout=1.5):
                pass

    def set_low_light(self, mode: str, strength: int) -> dict[str, Any]:
        self._low_light.configure(mode, strength)
        return self._low_light.status()

    @staticmethod
    def _fetch_json(url: str, timeout: float = 1.0) -> tuple[dict[str, Any], int, int]:
        started_ns = time.perf_counter_ns()
        with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        finished_ns = time.perf_counter_ns()
        if not isinstance(payload, dict):
            raise ValueError("Rover endpoint returned a non-object JSON payload")
        return payload, started_ns, finished_ns

    def _update_device_clock(self, payload: dict[str, Any], started_ns: int, finished_ns: int) -> int | None:
        try:
            device_clock_us = int(payload["clock_us"])
        except (KeyError, TypeError, ValueError):
            return None
        rtt_ns = finished_ns - started_ns
        candidate_offset_ns = (started_ns + finished_ns) // 2 - device_clock_us * 1000
        with self._lock:
            if self._imu_clock_offset_ns is None or self._imu_clock_rtt_ns is None:
                self._imu_clock_offset_ns = candidate_offset_ns
                self._imu_clock_rtt_ns = rtt_ns
            elif rtt_ns <= self._imu_clock_rtt_ns * 1.25:
                # Favor low-latency exchanges and smooth small Wi-Fi jitter.
                self._imu_clock_offset_ns = round(
                    self._imu_clock_offset_ns * 0.8 + candidate_offset_ns * 0.2
                )
                self._imu_clock_rtt_ns = min(self._imu_clock_rtt_ns, rtt_ns)
            return self._imu_clock_offset_ns

    def _consume_imu_payload(
        self, payload: dict[str, Any], started_ns: int, finished_ns: int
    ) -> int:
        offset_ns = self._update_device_clock(payload, started_ns, finished_ns)
        if offset_ns is None:
            return 0
        try:
            boot_id = int(payload["boot_id"])
            oldest_sequence = int(payload.get("oldest_sequence") or 0)
            rate_hz = int(payload.get("rate_hz") or 0)
            missed_deadlines = int(payload.get("missed_deadlines") or 0)
        except (KeyError, TypeError, ValueError):
            return 0
        rows = normalise_imu_samples(payload, offset_ns)
        with self._lock:
            if self._imu_boot_id is not None and boot_id != self._imu_boot_id:
                self._imu_sequence = 0
                self._imu_samples_dropped = 0
            expected_sequence = self._imu_sequence + 1
            if payload.get("dropped_before") is True and oldest_sequence > expected_sequence:
                self._imu_samples_dropped += oldest_sequence - expected_sequence
            self._imu_boot_id = boot_id
            self._imu_rate_hz = rate_hz
            self._imu_device_missed_total = missed_deadlines
            self._imu_stream_state = "live"
            self._imu_stream_error = None
            if rows:
                self._imu_sequence = int(rows[-1]["sequence"])
                if self._recording and self._imu_writer is not None:
                    self._imu_writer.writerows(rows)
                    self._imu_samples_recorded += len(rows)
                    if self._imu_file is not None:
                        self._imu_file.flush()
        return len(rows)

    def _sensor_loop(self, generation: int) -> None:
        try:
            sensor_url = f"{self.sensor_base_url}/api/environment"
            imu_base_url = f"{self.sensor_base_url}/api/imu"
        except ValueError as exc:
            with self._lock:
                self._imu_stream_state = "error"
                self._imu_stream_error = str(exc)
            return

        next_sensor_poll = 0.0
        while not self._stop_event.is_set() and generation == self._generation:
            loop_started = time.perf_counter()
            if loop_started >= next_sensor_poll:
                try:
                    from .sensor_esp import combine
                    environment, started_ns, finished_ns = self._fetch_json(sensor_url)
                    try:
                        imu, _, _ = self._fetch_json(imu_base_url)
                    except Exception:
                        imu = None
                    payload = combine(environment, imu)
                    self.update_sensor_snapshot(payload)
                    with self._lock:
                        self._imu_stream_state = "live" if payload.get("mpu_ok") else "unavailable"
                except Exception:
                    with self._lock:
                        self._imu_stream_state = "unavailable"
                next_sensor_poll = loop_started + 0.5
            self._stop_event.wait(0.4)

    def _inference_loop(self, generation: int) -> None:
        try:
            import torch
            from depth_anything_3.api import DepthAnything3
            from depth_anything_3.utils.visualize import visualize_depth

            if not torch.cuda.is_available():
                raise RuntimeError("CUDA is unavailable. Live DA3 requires the NVIDIA GPU.")

            with self._gpu_lock:
                model = DepthAnything3.from_pretrained(self.model_id).to("cuda").eval()
            if self._stop_event.is_set() or generation != self._generation:
                del model
                torch.cuda.empty_cache()
                return
            with self._model_lock:
                self._model = model
            with self._lock:
                self.model_state = "ready"

            last_sequence = -1
            last_inference_at = 0.0
            inference_counter = 0
            counter_started = time.perf_counter()
            while not self._stop_event.is_set() and generation == self._generation:
                with self._lock:
                    sequence = self._raw_sequence
                    frame = None if self._latest_frame is None else self._latest_frame.copy()
                now = time.perf_counter()
                if (
                    frame is None
                    or sequence == last_sequence
                    or now - last_inference_at < 1.0 / self.inference_fps
                ):
                    self._stop_event.wait(0.01)
                    continue

                started = time.perf_counter()
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                with self._gpu_lock:
                    prediction = model.inference(
                        [rgb_frame],
                        process_res=self.process_res,
                        process_res_method="upper_bound_resize",
                    )
                depth_rgb = visualize_depth(prediction.depth[0])
                depth_bgr = cv2.cvtColor(depth_rgb, cv2.COLOR_RGB2BGR)
                stats = depth_stats(
                    prediction.depth[0],
                    prediction.conf[0] if getattr(prediction, "conf", None) is not None else None,
                    getattr(prediction, "is_metric", 0),
                )
                encoded_ok, encoded = cv2.imencode(
                    ".jpg", depth_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 90]
                )
                if encoded_ok:
                    duration = time.perf_counter() - started
                    inference_counter += 1
                    fps_elapsed = time.perf_counter() - counter_started
                    with self._lock:
                        self._depth_jpeg = encoded.tobytes()
                        self._depth_sequence += 1
                        self._depth_stats = stats
                        self._latest_depth = np.asarray(prediction.depth[0]).copy()
                        self._latest_depth_raw_sequence = sequence
                        self._last_inference_ms = duration * 1000.0
                        if fps_elapsed >= 1.0:
                            self._depth_fps = inference_counter / fps_elapsed
                            inference_counter = 0
                            counter_started = time.perf_counter()
                    last_sequence = sequence
                    last_inference_at = time.perf_counter()
        except Exception as exc:
            with self._lock:
                if generation == self._generation:
                    self.model_state = "error"
                    self.error = f"DA3 live inference failed: {exc}"
        finally:
            with self._model_lock:
                if generation == self._generation:
                    self._model = None
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

    def _semantic_loop(self, generation: int) -> None:
        try:
            import torch
            from ultralytics import YOLOE

            if not torch.cuda.is_available():
                raise RuntimeError("CUDA is unavailable. Live semantics requires the NVIDIA GPU.")
            weights = ROOT_DIR / "yoloe-26s-seg.pt"
            if not weights.exists():
                raise RuntimeError(f"Missing semantic model: {weights.name}")
            with self._gpu_lock:
                model = YOLOE(str(weights))
                model.set_classes(LIVE_SEMANTIC_CLASSES, model.get_text_pe(LIVE_SEMANTIC_CLASSES))
                model.to("cuda")
            if self._stop_event.is_set() or generation != self._generation:
                del model
                torch.cuda.empty_cache()
                return
            with self._model_lock:
                self._semantic_model = model
            with self._lock:
                self.semantic_state = "ready"

            last_sequence = -1
            last_inference_at = 0.0
            inference_counter = 0
            counter_started = time.perf_counter()
            palette = [
                (35, 119, 255), (194, 211, 41), (255, 120, 168), (90, 198, 255),
                (130, 225, 95), (220, 170, 65), (235, 90, 200), (80, 220, 220),
            ]
            while not self._stop_event.is_set() and generation == self._generation:
                with self._lock:
                    sequence = self._raw_sequence
                    frame = None if self._latest_frame is None else self._latest_frame.copy()
                    camera_sequence = self._latest_camera_sequence
                    camera_timestamp_us = self._latest_camera_timestamp_us
                    depth = None if self._latest_depth is None else self._latest_depth.copy()
                    depth_sequence = self._latest_depth_raw_sequence
                now = time.perf_counter()
                if (
                    frame is None
                    or sequence == last_sequence
                    or now - last_inference_at < 1.0 / self.semantic_fps
                ):
                    self._stop_event.wait(0.01)
                    continue

                started = time.perf_counter()
                with self._gpu_lock:
                    result = model.predict(
                        frame, conf=0.18, imgsz=416, device=0, verbose=False
                    )[0]
                detections: list[dict[str, Any]] = []
                masks: list[np.ndarray] = []
                raw_masks = result.masks.data.cpu().numpy() if result.masks is not None else []
                for box, raw_mask in zip(result.boxes, raw_masks):
                    class_id = int(box.cls.item())
                    if class_id < 0 or class_id >= len(LIVE_SEMANTIC_CLASSES):
                        continue
                    mask = cv2.resize(
                        raw_mask, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_LINEAR
                    ) >= 0.5
                    if int(mask.sum()) < 30:
                        continue
                    item: dict[str, Any] = {
                        "label": LIVE_SEMANTIC_CLASSES[class_id],
                        "confidence": round(float(box.conf.item()), 4),
                        "bbox_xyxy": [round(float(value), 1) for value in box.xyxy[0].cpu().tolist()],
                        "_mask_index": len(masks),
                    }
                    if depth is not None and abs(sequence - depth_sequence) <= 12:
                        depth_mask = cv2.resize(
                            mask.astype(np.uint8), (depth.shape[1], depth.shape[0]),
                            interpolation=cv2.INTER_NEAREST,
                        ).astype(bool)
                        values = depth[depth_mask]
                        values = values[np.isfinite(values)]
                        if values.size:
                            item["relative_depth"] = round(float(np.median(values)), 3)
                    detections.append(item)
                    masks.append(mask)

                tracked = self._semantic_tracker.update(detections)
                overlay = frame.copy()
                for item in tracked:
                    mask = masks[int(item["_mask_index"])]
                    colour = palette[(int(item["track_id"]) - 1) % len(palette)]
                    overlay[mask] = (
                        0.58 * overlay[mask] + 0.42 * np.asarray(colour, dtype=np.float32)
                    ).astype(np.uint8)
                    x1, y1, x2, y2 = (int(value) for value in item["bbox_xyxy"])
                    cv2.rectangle(overlay, (x1, y1), (x2, y2), colour, 2, cv2.LINE_AA)
                    caption = f'{item["object_id"]} {round(item["confidence"] * 100)}%'
                    if "relative_depth" in item:
                        caption += f'  z {item["relative_depth"]:.2f} rel'
                    (text_width, text_height), _ = cv2.getTextSize(
                        caption, cv2.FONT_HERSHEY_SIMPLEX, 0.46, 1
                    )
                    label_top = max(0, y1 - text_height - 10)
                    cv2.rectangle(
                        overlay, (x1, label_top), (min(frame.shape[1] - 1, x1 + text_width + 8), y1),
                        colour, -1,
                    )
                    cv2.putText(
                        overlay, caption, (x1 + 4, max(text_height + 1, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.46, (8, 10, 12), 1, cv2.LINE_AA,
                    )

                cv2.putText(
                    overlay, "LIVE SEMANTICS  |  VIEW-LOCAL TRACKS",
                    (12, frame.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                    (225, 235, 240), 1, cv2.LINE_AA,
                )
                encoded_ok, encoded = cv2.imencode(
                    ".jpg", overlay, [int(cv2.IMWRITE_JPEG_QUALITY), 90]
                )
                if encoded_ok:
                    duration = time.perf_counter() - started
                    inference_counter += 1
                    fps_elapsed = time.perf_counter() - counter_started
                    observations = [
                        {
                            **{key: value for key, value in item.items() if not key.startswith("_")},
                            "camera_sequence": camera_sequence,
                            "camera_timestamp_us": camera_timestamp_us,
                            "world_anchored": False,
                        }
                        for item in tracked
                    ]
                    with self._lock:
                        self._semantic_jpeg = encoded.tobytes()
                        self._semantic_sequence += 1
                        self._semantic_objects = observations
                        self._last_semantic_ms = duration * 1000.0
                        if fps_elapsed >= 1.0:
                            self._semantic_fps_actual = inference_counter / fps_elapsed
                            inference_counter = 0
                            counter_started = time.perf_counter()
                    last_sequence = sequence
                    last_inference_at = time.perf_counter()
        except Exception as exc:
            with self._lock:
                if generation == self._generation:
                    self.semantic_state = "error"
                    self.semantic_error = f"Live semantic inference failed: {exc}"
        finally:
            with self._model_lock:
                if generation == self._generation:
                    self._semantic_model = None
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

    @staticmethod
    def _sensor_is_stable(snapshot: dict[str, Any] | None) -> bool:
        if not snapshot or snapshot.get("mpu_ok") is not True:
            return False
        try:
            accel = snapshot["accel_g"]
            gyro = snapshot["gyro_dps"]
            acceleration_magnitude = math.sqrt(
                float(accel["x"]) ** 2 + float(accel["y"]) ** 2 + float(accel["z"]) ** 2
            )
            angular_rate = math.sqrt(
                float(gyro["x"]) ** 2 + float(gyro["y"]) ** 2 + float(gyro["z"]) ** 2
            )
        except (KeyError, TypeError, ValueError):
            return False
        return abs(acceleration_magnitude - 1.0) < 0.12 and angular_rate < 12.0

    def update_sensor_snapshot(self, payload: dict[str, Any]) -> None:
        snapshot = json.loads(json.dumps(payload))
        snapshot["dashboard_received_at"] = utc_now()
        snapshot["capture_stable"] = self._sensor_is_stable(snapshot)
        with self._lock:
            self._sensor_snapshot = snapshot
            self._sensor_snapshot_received_ns = time.perf_counter_ns()
            if self._recording and self._sensor_file is not None:
                try:
                    self._sensor_file.write(json.dumps({"captured_at": utc_now(), "sensors": snapshot}, allow_nan=False) + "\n")
                    self._sensor_samples_recorded += 1
                except (OSError, ValueError, TypeError):
                    pass

    def sensor_snapshot(self, maximum_age_seconds: float = 1.0) -> dict[str, Any] | None:
        with self._lock:
            if self._sensor_snapshot is None:
                return None
            age_ns = time.perf_counter_ns() - self._sensor_snapshot_received_ns
            if age_ns > maximum_age_seconds * 1_000_000_000:
                return None
            return json.loads(json.dumps(self._sensor_snapshot))

    def autonomy_snapshot(self) -> dict[str, Any] | None:
        """Return one coherent, copy-safe perception snapshot for local autonomy."""
        with self._lock:
            jpeg = self._original_jpeg or self._raw_jpeg
            if jpeg is None or self._frame_width <= 0 or self._frame_height <= 0:
                return None
            sensors = (
                json.loads(json.dumps(self._sensor_snapshot))
                if self._sensor_snapshot is not None
                else None
            )
            sensor_age_seconds = (
                (time.perf_counter_ns() - self._sensor_snapshot_received_ns) / 1_000_000_000
                if self._sensor_snapshot is not None and self._sensor_snapshot_received_ns
                else None
            )
            depth = None
            if (
                self._latest_depth is not None
                and abs(self._raw_sequence - self._latest_depth_raw_sequence) <= 12
            ):
                depth = self._latest_depth.copy()
            return {
                "jpeg": bytes(jpeg),
                "width": self._frame_width,
                "height": self._frame_height,
                "camera_sequence": self._latest_camera_sequence,
                "semantic_objects": json.loads(json.dumps(self._semantic_objects)),
                "sensors": sensors,
                "sensor_age_seconds": sensor_age_seconds,
                "depth": depth,
            }

    def start_recording(
        self, requested_name: str, keyframe_fps: float, stable_only: bool = False
    ) -> str:
        with self._lock:
            if self.state not in {"live", "reconnecting"} or self._latest_frame is None:
                raise RuntimeError("Connect to a working camera stream before recording")
            if self._recording:
                raise RuntimeError("A recording is already active")

        base = safe_slug(requested_name, datetime.now().strftime("capture_%Y%m%d_%H%M%S"))
        name = base
        index = 2
        folder = path_in(DATA_DIR, name)
        while folder.exists() and any(folder.iterdir()):
            name = f"{base}_{index}"
            folder = path_in(DATA_DIR, name)
            index += 1
        folder.mkdir(parents=True, exist_ok=True)

        imu_file = (folder / "imu.csv").open("w", newline="", encoding="utf-8")
        imu_writer = csv.DictWriter(imu_file, fieldnames=IMU_CSV_FIELDS)
        imu_writer.writeheader()
        sensor_file = (folder / "sensors.jsonl").open("w", encoding="utf-8")

        video_writer = cv2.VideoWriter(
            str(folder / "video.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 12.0,
            (self._frame_width, self._frame_height),
        )
        video_error = None
        if not video_writer.isOpened():
            video_writer.release()
            video_writer = None
            video_error = "MP4 encoder unavailable; camera keyframes were still saved"

        with self._lock:
            self._recording = True
            self._video_writer = video_writer
            self._video_frames = 0
            self._video_error = video_error
            self._last_video_at = 0.0
            self._sensor_file = sensor_file
            self._sensor_samples_recorded = 0
            self._recording_name = name
            self._recording_dir = folder
            self._recording_started_at = utc_now()
            self._keyframe_fps = keyframe_fps
            self._keyframe_count = 0
            self._last_keyframe_at = 0.0
            self._stable_only = stable_only
            self._motion_skipped = 0
            self._telemetry_frames = 0
            self._imu_samples_recorded = 0
            self._imu_samples_dropped = 0
            self._imu_device_missed_at_record_start = self._imu_device_missed_total
            self._imu_file = imu_file
            self._imu_writer = imu_writer
            manifest = self._manifest("recording")
        write_json(folder / "capture.json", manifest)
        return name

    def stop_recording(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._recording or self._recording_dir is None:
                return None
            folder = self._recording_dir
            manifest = self._manifest("complete")
            manifest["completed_at"] = utc_now()
            self._recording = False
            self._recording_name = None
            self._recording_dir = None
            self._recording_started_at = None
            imu_file = self._imu_file
            sensor_file = self._sensor_file
            self._sensor_file = None
            video_writer = self._video_writer
            self._video_writer = None
            self._imu_file = None
            self._imu_writer = None
            if imu_file is not None:
                imu_file.flush()
                imu_file.close()
            if sensor_file is not None:
                sensor_file.flush()
                sensor_file.close()
            if video_writer is not None:
                video_writer.release()
                manifest["video_frames"] = self._video_frames
                manifest["video_file"] = "video.mp4" if (folder / "video.mp4").is_file() else None
        write_json(folder / "capture.json", manifest)
        return manifest

    def _manifest(self, state: str) -> dict[str, Any]:
        return {
            "name": self._recording_name,
            "state": state,
            "started_at": self._recording_started_at,
            "stream_url": self.stream_url,
            "sensor_base_url": self.sensor_base_url,
            "model_id": self.model_id,
            "depth_enabled": self.depth_enabled,
            "semantic_enabled": self.semantic_enabled,
            "semantic_fps": self.semantic_fps,
            "camera_profile": self.camera_profile,
            "rotation": self.rotation,
            "low_light": self._low_light.status(),
            "capture_fps": round(self._capture_fps, 1),
            "process_res": self.process_res,
            "inference_fps": self.inference_fps,
            "keyframe_fps": self._keyframe_fps,
            "frames": self._keyframe_count,
            "video_file": "video.mp4" if self._video_writer is not None else None,
            "video_frames": self._video_frames,
            "video_fps": 12,
            "video_error": self._video_error,
            "sensor_file": "sensors.jsonl",
            "sensor_samples": self._sensor_samples_recorded,
            "stable_only": self._stable_only,
            "motion_skipped": self._motion_skipped,
            "telemetry_frames": self._telemetry_frames,
            "vio_dataset_version": 1,
            "imu_file": "imu.csv",
            "imu_rate_hz": self._imu_rate_hz,
            "imu_boot_id": self._imu_boot_id,
            "imu_samples": self._imu_samples_recorded,
            "imu_samples_dropped": self._imu_samples_dropped,
            "imu_device_deadlines_missed": max(
                0, self._imu_device_missed_total - self._imu_device_missed_at_record_start
            ),
            "camera_timestamp_source": (
                "esp32_frame_header"
                if self._latest_camera_timestamp_us is not None
                else "host_receive_clock_estimate"
            ),
            "frame_width": self._frame_width,
            "frame_height": self._frame_height,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self.state,
                "model_state": self.model_state,
                "error": self.error,
                "stream_url": self.stream_url,
                "sensor_base_url": self.sensor_base_url,
                "model_id": self.model_id,
                "depth_enabled": self.depth_enabled,
                "semantic_enabled": self.semantic_enabled,
                "semantic_state": self.semantic_state,
                "semantic_error": self.semantic_error,
                "semantic_fps_target": self.semantic_fps,
                "semantic_fps": round(self._semantic_fps_actual, 1),
                "semantic_inference_ms": round(self._last_semantic_ms),
                "semantic_objects": json.loads(json.dumps(self._semantic_objects)),
                "semantic_pose_state": "view-local",
                "camera_profile": self.camera_profile,
                "rotation": self.rotation,
                "camera_profile_error": self.camera_profile_error,
                "low_light": self._low_light.status(),
                "process_res": self.process_res,
                "inference_fps": self.inference_fps,
                "connected_at": self.connected_at,
                "capture_fps": round(self._capture_fps, 1),
                "depth_fps": round(self._depth_fps, 1),
                "inference_ms": round(self._last_inference_ms),
                "depth_stats": self._depth_stats,
                "width": self._frame_width,
                "height": self._frame_height,
                "recording": self._recording,
                "recording_name": self._recording_name,
                "recording_started_at": self._recording_started_at,
                "frames_saved": self._keyframe_count,
                "keyframe_fps": self._keyframe_fps,
                "stable_only": self._stable_only,
                "motion_skipped": self._motion_skipped,
                "imu_stream_state": self._imu_stream_state,
                "imu_stream_error": self._imu_stream_error,
                "imu_rate_hz": self._imu_rate_hz,
                "imu_sequence": self._imu_sequence,
                "imu_samples_recorded": self._imu_samples_recorded,
                "imu_samples_dropped": self._imu_samples_dropped,
                "imu_device_deadlines_missed": max(
                    0, self._imu_device_missed_total - self._imu_device_missed_at_record_start
                ),
                "camera_timestamp_us": self._latest_camera_timestamp_us,
                "camera_sequence": self._latest_camera_sequence,
            }

    def mjpeg(self, kind: str) -> Iterator[bytes]:
        last_sequence = -1
        while True:
            with self._lock:
                if kind == "depth":
                    payload = self._depth_jpeg
                    sequence = self._depth_sequence
                elif kind == "semantic":
                    payload = self._semantic_jpeg
                    sequence = self._semantic_sequence
                elif kind == "original":
                    payload = self._original_jpeg
                    sequence = self._raw_sequence
                else:
                    payload = self._raw_jpeg
                    sequence = self._raw_sequence
            if payload is None or sequence == last_sequence:
                time.sleep(0.03)
                continue
            last_sequence = sequence
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\nCache-Control: no-cache\r\n\r\n"
                + payload
                + b"\r\n"
            )


class ModelDownloads:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def cached_ids(self) -> set[str]:
        try:
            from huggingface_hub import scan_cache_dir

            return {repo.repo_id for repo in scan_cache_dir().repos}
        except Exception:
            return set()

    def models(self) -> list[dict[str, Any]]:
        cached = self.cached_ids()
        with self._lock:
            jobs = {key: value.copy() for key, value in self._jobs.items()}
        return [
            {
                **model,
                "cached": model["id"] in cached,
                "download": jobs.get(model["id"]),
            }
            for model in MODEL_CATALOG
        ]

    def start(self, model_id: str) -> None:
        if model_id not in MODEL_IDS:
            raise ValueError("Unknown model")
        with self._lock:
            current = self._jobs.get(model_id)
            if current and current["state"] == "downloading":
                return
            self._jobs[model_id] = {
                "state": "downloading",
                "started_at": utc_now(),
                "error": None,
            }
        threading.Thread(target=self._download, args=(model_id,), daemon=True).start()

    def _download(self, model_id: str) -> None:
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(
                repo_id=model_id,
                allow_patterns=["*.json", "*.safetensors", "*.txt"],
            )
            with self._lock:
                self._jobs[model_id] = {
                    "state": "complete",
                    "completed_at": utc_now(),
                    "error": None,
                }
        except Exception as exc:
            with self._lock:
                self._jobs[model_id] = {
                    "state": "error",
                    "completed_at": utc_now(),
                    "error": str(exc),
                }


class ReconstructionJobs:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._active_job: str | None = None
        self._process: subprocess.Popen[str] | None = None

    def start(
        self,
        capture_name: str,
        model_id: str,
        process_res: int,
        conf_thresh_percentile: float = 55.0,
        num_max_points: int = 1_000_000,
        show_cameras: bool = False,
        frames: list[str] | None = None,
    ) -> dict[str, Any]:
        if model_id not in MODEL_IDS:
            raise ValueError("Unknown model")
        capture_dir = path_in(DATA_DIR, capture_name)
        available = {path.name for path in image_files(capture_dir)}

        selected: list[str] | None = None
        if frames:
            # Keep only real frames of this capture, in capture order.
            requested = set(frames)
            selected = [name for name in sorted(available) if name in requested]
            if len(selected) < 2:
                raise ValueError("Select at least two valid frames for reconstruction")
        elif len(available) < 2:
            raise ValueError("At least two captured images are required")

        count = len(selected) if selected is not None else len(available)

        with self._lock:
            if self._active_job:
                active = self._jobs.get(self._active_job, {})
                if active.get("state") in {"queued", "running", "cancelling"}:
                    raise RuntimeError("Another reconstruction is already running")

            run_base = safe_slug(capture_name, "reconstruction")
            run_name = run_base
            suffix = 2
            while path_in(RUNS_DIR, run_name).exists():
                run_name = f"{run_base}_{suffix}"
                suffix += 1
            job_id = uuid.uuid4().hex[:12]
            job = {
                "id": job_id,
                "state": "queued",
                "capture": capture_name,
                "run_name": run_name,
                "model_id": model_id,
                "process_res": process_res,
                "conf_thresh_percentile": conf_thresh_percentile,
                "num_max_points": num_max_points,
                "show_cameras": show_cameras,
                "frames": selected,
                "images": count,
                "progress": 0,
                "stage": "Queued",
                "created_at": utc_now(),
                "started_at": None,
                "completed_at": None,
                "error": None,
                "logs": [],
            }
            self._jobs[job_id] = job
            self._active_job = job_id
        threading.Thread(target=self._run, args=(job_id,), daemon=True).start()
        return job.copy()

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            capture_dir = path_in(DATA_DIR, job["capture"])
            run_dir = path_in(RUNS_DIR, job["run_name"])
            selected_frames = job.get("frames")
            job["state"] = "running"
            job["stage"] = "Starting DA3"
            job["started_at"] = utc_now()

        # When only a subset of frames is chosen, stage copies in a temp folder
        # so the DA3 `images` command (which reads a whole directory) sees only
        # those frames. The staging dir is removed in the finally block.
        staging_dir: Path | None = None
        images_dir = capture_dir
        if selected_frames:
            staging_dir = Path(tempfile.mkdtemp(prefix="da3_input_", dir=str(ROOT_DIR)))
            for name in selected_frames:
                source = capture_dir / name
                if source.is_file():
                    shutil.copy2(source, staging_dir / name)
            images_dir = staging_dir

        command = [
            sys.executable,
            "-m",
            "depth_anything_3.cli",
            "images",
            str(images_dir),
            "--model-dir",
            job["model_id"],
            "--export-format",
            "glb",
            "--export-dir",
            str(run_dir),
            "--process-res",
            str(job["process_res"]),
            # Quality levers exposed in the reconstruct dialog. A higher
            # confidence percentile drops low-confidence floating/noise points;
            # hiding camera wireframes declutters the exported scene.
            "--conf-thresh-percentile",
            str(job["conf_thresh_percentile"]),
            "--num-max-points",
            str(job["num_max_points"]),
            "--show-cameras" if job["show_cameras"] else "--no-show-cameras",
        ]
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        dependency_paths = [
            str(ROOT_DIR / "vision" / ".venv" / "Lib" / "site-packages"),
            str(ROOT_DIR / "third_party" / "depth-anything-3" / "src"),
            str(ROOT_DIR),
        ]
        if env.get("PYTHONPATH"):
            dependency_paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(dependency_paths)
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                command,
                cwd=ROOT_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creation_flags,
            )
            with self._lock:
                self._process = process
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.rstrip()
                if line:
                    self._append_log(job_id, line)
                    self._parse_progress(job_id, line)
            return_code = process.wait()
            with self._lock:
                job = self._jobs[job_id]
                if job["state"] in {"cancelling", "cancelled"}:
                    job["state"] = "cancelled"
                    job["stage"] = "Cancelled"
                elif return_code == 0 and (run_dir / "scene.glb").is_file():
                    job["state"] = "complete"
                    job["stage"] = "Complete"
                    job["progress"] = 100
                else:
                    job["state"] = "error"
                    job["stage"] = "Failed"
                    job["error"] = f"DA3 exited with code {return_code}"
                job["completed_at"] = utc_now()
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job["state"] = "error"
                job["stage"] = "Failed"
                job["error"] = str(exc)
                job["completed_at"] = utc_now()
        finally:
            if staging_dir is not None:
                shutil.rmtree(staging_dir, ignore_errors=True)
            with self._lock:
                self._process = None
                if self._active_job == job_id:
                    self._active_job = None

    def _append_log(self, job_id: str, line: str) -> None:
        with self._lock:
            logs: list[str] = self._jobs[job_id]["logs"]
            logs.append(line)
            del logs[:-160]

    def _parse_progress(self, job_id: str, line: str) -> None:
        lower = line.lower()
        progress = None
        stage = None
        if "loading model" in lower or "model.safetensors" in lower:
            progress, stage = 10, "Loading model"
        elif "running inference" in lower:
            progress, stage = 25, "Preparing images"
        elif "processed images done" in lower:
            progress, stage = 40, "Images prepared"
        elif "model forward pass done" in lower:
            progress, stage = 78, "Depth and camera poses complete"
        elif "exporting to glb" in lower:
            progress, stage = 88, "Building 3D model"
        elif "export results done" in lower:
            progress, stage = 97, "Finalizing files"
        if progress is not None:
            with self._lock:
                job = self._jobs[job_id]
                job["progress"] = max(job["progress"], progress)
                job["stage"] = stage

    def cancel(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ValueError("Unknown job")
            if job["state"] not in {"queued", "running"}:
                return
            job["state"] = "cancelling"
            job["stage"] = "Stopping process"
            process = self._process
        if process and process.poll() is None:
            try:
                if os.name == "nt":
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                    process.wait(timeout=3.0)
                else:
                    process.terminate()
                    process.wait(timeout=3.0)
            except Exception:
                process.kill()

    def dismiss(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ValueError("Unknown job")
            if job["state"] in {"queued", "running", "cancelling"}:
                raise RuntimeError("Stop the job before dismissing it")
            del self._jobs[job_id]

    def status(self) -> dict[str, Any]:
        with self._lock:
            jobs = []
            for job in sorted(
                self._jobs.values(), key=lambda item: item["created_at"], reverse=True
            ):
                summary = job.copy()
                # The full frame list is an internal detail; expose only its size.
                summary.pop("frames", None)
                summary["selected_frames"] = len(job["frames"]) if job.get("frames") else 0
                jobs.append(summary)
            return {"active_job": self._active_job, "jobs": jobs}

    def shutdown(self) -> None:
        with self._lock:
            active = self._active_job
        if active:
            self.cancel(active)


live_pipeline = LivePipeline()
model_downloads = ModelDownloads()
reconstruction_jobs = ReconstructionJobs()


def list_captures() -> list[dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    captures: list[dict[str, Any]] = []
    for folder in DATA_DIR.iterdir():
        if not folder.is_dir():
            continue
        images = image_files(folder)
        if not images or (not (folder / "capture.json").is_file() and not any(image.name.startswith("frame_") for image in images)):
            continue
        stat = folder.stat()
        manifest = read_json(folder / "capture.json")
        captures.append(
            {
                "name": folder.name,
                "images": len(images),
                "size_bytes": folder_size(folder),
                "updated_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "cover_url": f"/api/captures/{folder.name}/photos/{images[0].name}",
                "manifest": manifest,
            }
        )
    return sorted(captures, key=lambda item: item["updated_at"], reverse=True)


def list_runs() -> list[dict[str, Any]]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    for folder in RUNS_DIR.iterdir():
        if not folder.is_dir():
            continue
        glb = folder / "scene.glb"
        if not glb.is_file():
            continue
        thumbnail = folder / "scene.jpg"
        semantic_registry = read_json(folder / "objects.json")
        semantic = isinstance(semantic_registry, dict) and isinstance(semantic_registry.get("objects"), list)
        stat = glb.stat()
        runs.append(
            {
                "name": folder.name,
                "size_bytes": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "model_url": f"/api/runs/{folder.name}/model",
                "download_url": f"/api/runs/{folder.name}/model?download=1",
                "thumbnail_url": (
                    f"/api/runs/{folder.name}/thumbnail" if thumbnail.is_file() else None
                ),
                "semantic": semantic,
                "object_count": sum(
                    item.get("review", {}).get("status", "candidate") != "rejected"
                    for item in semantic_registry["objects"]
                ) if semantic else 0,
                "objects_url": f"/api/runs/{folder.name}/semantic/objects.json" if semantic else None,
                "report_url": f"/api/runs/{folder.name}/semantic/report.html" if semantic and (folder / "report.html").is_file() else None,
            }
        )
    return sorted(runs, key=lambda item: item["updated_at"], reverse=True)


def rename_run(old_name: str, new_name: str) -> str:
    """Rename a reconstruction run folder, returning the final (unique) name."""
    source = path_in(RUNS_DIR, old_name)
    if not source.is_dir() or not (source / "scene.glb").is_file():
        raise ValueError("Reconstruction not found")
    base = safe_slug(new_name, "")
    if not base:
        raise ValueError("Enter a valid name")
    if base == old_name:
        return old_name
    target = path_in(RUNS_DIR, base)
    final = base
    suffix = 2
    while target.exists():
        final = f"{base}_{suffix}"
        target = path_in(RUNS_DIR, final)
        suffix += 1
    source.rename(target)
    return final
