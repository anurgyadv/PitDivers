from __future__ import annotations

import base64
import json
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

import numpy as np

from .rover_control import RoverControlError, normalize_rover_url, rover_request


def normalize_ollama_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Enter a valid Ollama URL")
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")


def ollama_models(base_url: str) -> list[str]:
    origin = normalize_ollama_url(base_url)
    request = Request(f"{origin}/api/tags", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=2.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Ollama unavailable: {exc}") from exc
    return [str(item.get("name")) for item in payload.get("models", []) if item.get("name")]


class AutonomyController:
    """Bounded visual servoing with optional Ollama vision observations."""

    def __init__(self, pipeline: Any) -> None:
        self.pipeline = pipeline
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._rover_url: str | None = None
        self._api_key = ""
        self._target = ""
        self._mission = "explore"
        self._speed = 120
        self._use_llama = False
        self._ollama_url = "http://127.0.0.1:11434"
        self._model = "llama3.2-vision:11b"
        self._state = "idle"
        self._action = "stopped"
        self._message = "No autonomous task"
        self._started_at: str | None = None
        self._steps = 0
        self._last_detection: dict[str, Any] | None = None
        self._last_model_result: dict[str, Any] | None = None
        self._logs: deque[dict[str, Any]] = deque(maxlen=300)
        self._log_id = 0

    def _log(self, message: str, level: str = "info") -> None:
        with self._lock:
            self._log_id += 1
            self._logs.append({
                "id": self._log_id,
                "at": datetime.now(timezone.utc).isoformat(),
                "level": level,
                "message": message,
            })

    def start(
        self,
        *,
        rover_url: str,
        api_key: str,
        mission: str,
        target: str,
        speed: int,
        use_llama: bool,
        ollama_url: str,
        model: str,
    ) -> dict:
        origin = normalize_rover_url(rover_url)
        if mission not in {"explore", "find"}:
            raise ValueError("Mission must be explore or find")
        target = target.strip()
        if mission == "find" and not target:
            raise ValueError("Enter an object to find")
        if mission == "explore":
            target = "ROOM"
        if not api_key.strip():
            raise ValueError("Enter the motion ESP API key")
        if self.pipeline.autonomy_snapshot() is None:
            raise RuntimeError("Connect a working camera stream before starting autonomy")
        initial_snapshot = self.pipeline.autonomy_snapshot()
        if mission == "explore":
            if (initial_snapshot or {}).get("depth") is None:
                raise RuntimeError("Explore mode requires DA3 depth to be ready")
        ollama_origin = normalize_ollama_url(ollama_url)
        if use_llama and model not in ollama_models(ollama_origin):
            raise RuntimeError(f"Ollama model '{model}' is not installed")

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("An autonomous task is already running")
            self._rover_url = origin
            self._api_key = api_key
            self._mission = mission
            self._target = target
            self._speed = max(170, speed) if mission == "explore" else speed
            self._use_llama = use_llama
            self._ollama_url = ollama_origin
            self._model = model
            self._state = "starting"
            self._action = "stopped"
            self._message = "Preparing room exploration" if mission == "explore" else f"Preparing to find {target}"
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._steps = 0
            self._last_detection = None
            self._last_model_result = None
            self._logs.clear()
            self._stop_event.clear()

        task_description = "explore room" if mission == "explore" else f"find '{target}'"
        self._log(f"Task requested: {task_description} at speed {self._speed}")
        self._log(f"Camera ready; detector=YOLOE, vision fallback={model if use_llama else 'disabled'}")
        if mission == "explore":
            sensors = (initial_snapshot or {}).get("sensors") or {}
            sensor_age = (initial_snapshot or {}).get("sensor_age_seconds")
            if not sensors.get("sonar_ok") or sensor_age is None or sensor_age > 1.5:
                self._log(
                    "SONAR unavailable: using depth-only exploration with shorter forward leases",
                    "warning",
                )
        self._log(f"Switching motion controller at {origin} to AI mode")
        try:
            rover_request(origin, "/mode", method="POST", params={"value": "ai"})
        except Exception as exc:
            self._log(f"Could not enter AI mode: {exc}", "error")
            raise
        self._log(f"AI mode accepted; starting bounded {mission} loop", "success")
        thread = threading.Thread(target=self._run, daemon=True, name="pitdivers-autonomy")
        with self._lock:
            self._thread = thread
            self._state = "running"
            self._message = "Exploring room" if mission == "explore" else f"Searching for {target}"
        thread.start()
        return self.status()

    def stop(self, *, return_to_human: bool = True) -> dict:
        self._stop_event.set()
        with self._lock:
            thread = self._thread
            rover_url = self._rover_url
            api_key = self._api_key
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        if rover_url:
            self._log("Stop requested; sending motor stop")
            self._send_stop(rover_url, api_key)
            if return_to_human:
                try:
                    rover_request(rover_url, "/mode", method="POST", params={"value": "human"}, timeout=0.8)
                except (ValueError, RoverControlError):
                    pass
        with self._lock:
            self._thread = None
            self._state = "idle"
            self._action = "stopped"
            self._message = "Autonomy stopped"
        return self.status()

    def status(self) -> dict:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            return {
                "state": self._state,
                "running": running,
                "target": self._target or None,
                "mission": self._mission,
                "action": self._action,
                "message": self._message,
                "steps": self._steps,
                "started_at": self._started_at,
                "use_llama": self._use_llama,
                "model": self._model,
                "detection": self._last_detection,
                "model_result": self._last_model_result,
                "logs": list(self._logs),
            }

    def _set_status(self, *, state: str | None = None, action: str | None = None,
                    message: str | None = None, detection: dict[str, Any] | None = None) -> None:
        with self._lock:
            if state is not None:
                self._state = state
            if action is not None:
                self._action = action
            if message is not None:
                self._message = message
            if detection is not None:
                self._last_detection = detection

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"X-API-Key": api_key}

    def _move(self, rover_url: str, api_key: str, direction: str, duration_ms: int) -> None:
        payload = rover_request(
            rover_url,
            "/api/move",
            method="POST",
            params={"direction": direction, "speed": self._speed, "duration_ms": duration_ms},
            headers=self._headers(api_key),
            timeout=1.0,
        )
        if payload.get("ok") is False or payload.get("motion") not in {None, direction}:
            raise RuntimeError(f"Motion controller rejected {direction}: {payload}")

    @staticmethod
    def _depth_clearance(snapshot: dict[str, Any]) -> dict[str, float] | None:
        """Median relative clearance across three forward-looking image zones."""
        depth = snapshot.get("depth")
        if not isinstance(depth, np.ndarray) or depth.ndim != 2:
            return None
        height, width = depth.shape
        view = depth[int(height * 0.22):int(height * 0.78), int(width * 0.08):int(width * 0.92)]
        if view.size == 0:
            return None
        zones = np.array_split(view, 3, axis=1)
        result: dict[str, float] = {}
        for name, zone in zip(("left", "center", "right"), zones):
            valid = zone[np.isfinite(zone) & (zone > 0)]
            if valid.size < 32:
                return None
            result[name] = float(np.median(valid))
        return result

    @staticmethod
    def _safer_turn(clearance: dict[str, float] | None, step: int) -> str:
        if clearance and abs(clearance["left"] - clearance["right"]) > 0.01:
            return "left" if clearance["left"] > clearance["right"] else "right"
        return "left" if (step // 3) % 2 == 0 else "right"

    def _send_stop(self, rover_url: str, api_key: str) -> None:
        try:
            rover_request(
                rover_url, "/api/stop", method="POST",
                headers=self._headers(api_key), timeout=0.8,
            )
        except (ValueError, RoverControlError):
            try:
                rover_request(rover_url, "/stop", timeout=0.8)
            except (ValueError, RoverControlError):
                pass

    def _semantic_detection(self, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        target = self._target.casefold()
        candidates = []
        for item in snapshot.get("semantic_objects", []):
            label = str(item.get("label", "")).casefold()
            if target in label or label in target:
                candidates.append(item)
        if not candidates:
            return None
        item = max(candidates, key=lambda candidate: float(candidate.get("confidence", 0)))
        x1, y1, x2, y2 = (float(value) for value in item["bbox_xyxy"])
        width = max(1.0, float(snapshot["width"]))
        height = max(1.0, float(snapshot["height"]))
        return {
            "source": "semantic",
            "label": item.get("label"),
            "confidence": item.get("confidence"),
            "center_x": ((x1 + x2) / 2.0) / width,
            "center_y": ((y1 + y2) / 2.0) / height,
            "width": (x2 - x1) / width,
            "height": (y2 - y1) / height,
        }

    def _llama_detection(self, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        sensors = snapshot.get("sensors") or {}
        telemetry = {
            key: sensors.get(key)
            for key in ("distance_cm", "sonar_ok", "temperature_c", "humidity_pct", "pitch_deg", "roll_deg")
            if key in sensors
        }
        prompt = (
            f"Locate the object described as '{self._target}'. Return JSON only with keys "
            "found, label, confidence, center_x, center_y, width, height, description. "
            "Coordinates and sizes must be numbers from 0 to 1. If uncertain set found false. "
            f"Current rover telemetry is {json.dumps(telemetry, separators=(',', ':'))}. "
            "The supervised controller can issue only short forward, backward, left, right, and stop "
            "commands through the authenticated rover movement endpoint. You are identifying the target; "
            "the safety controller, sonar guard, and command lease decide whether the rover may move."
        )
        payload = {
            "model": self._model,
            "stream": False,
            "format": "json",
            "keep_alive": "15m",
            "messages": [{
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(snapshot["jpeg"]).decode("ascii")],
            }],
            "options": {"temperature": 0, "num_predict": 160},
        }
        request = Request(
            f"{self._ollama_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        request_started = time.monotonic()
        self._log(f"Sending camera frame and telemetry to {self._model} (rover remains stopped)", "model")
        try:
            with urlopen(request, timeout=120.0) as response:
                result = json.loads(response.read().decode("utf-8"))
            observation = json.loads(result["message"]["content"])
        except (HTTPError, URLError, TimeoutError, OSError, KeyError, json.JSONDecodeError) as exc:
            elapsed = time.monotonic() - request_started
            raise RuntimeError(f"Ollama vision request failed after {elapsed:.1f}s: {exc}") from exc
        self._log(f"{self._model} responded in {time.monotonic() - request_started:.1f}s", "model")
        with self._lock:
            self._last_model_result = observation
        if not observation.get("found"):
            self._log(f"{self._model}: target not found in this frame", "model")
            return None
        try:
            detection = {
                "source": "ollama",
                "label": str(observation.get("label") or self._target),
                "confidence": float(observation.get("confidence", 0)),
                "center_x": float(observation["center_x"]),
                "center_y": float(observation["center_y"]),
                "width": float(observation["width"]),
                "height": float(observation["height"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Ollama returned invalid object coordinates") from exc
        if not all(0.0 <= float(detection[key]) <= 1.0 for key in ("center_x", "center_y", "width", "height")):
            raise RuntimeError("Ollama returned coordinates outside 0..1")
        self._log(
            f"{self._model}: found {detection['label']} "
            f"confidence={detection['confidence']:.2f} x={detection['center_x']:.2f} height={detection['height']:.2f}",
            "model",
        )
        return detection

    def _run(self) -> None:
        if self._mission == "explore":
            self._run_explore()
        else:
            self._run_find()

    def _run_explore(self) -> None:
        with self._lock:
            rover_url = self._rover_url
            api_key = self._api_key
        if not rover_url:
            return

        try:
            while not self._stop_event.is_set():
                with self._lock:
                    steps = self._steps
                if steps >= 120:
                    self._send_stop(rover_url, api_key)
                    self._log("Exploration limit reached after 120 steps", "success")
                    self._set_status(
                        state="complete", action="stopped",
                        message="Completed a bounded room exploration",
                    )
                    return

                snapshot = self.pipeline.autonomy_snapshot()
                if snapshot is None:
                    raise RuntimeError("Camera stream was lost")
                sensors = snapshot.get("sensors") or {}
                sensor_age = snapshot.get("sensor_age_seconds")
                distance_cm = None
                if sensors.get("sonar_ok") and sensor_age is not None and sensor_age <= 1.5:
                    try:
                        distance_cm = float(sensors["distance_cm"])
                    except (KeyError, TypeError, ValueError):
                        distance_cm = None

                clearance = self._depth_clearance(snapshot)
                if clearance is None:
                    raise RuntimeError("DA3 depth became unavailable or stale")

                # Never reverse automatically: one forward-facing sonar cannot
                # guarantee that the space behind the rover is clear.
                if distance_cm is not None and distance_cm <= 55.0:
                    self._send_stop(rover_url, api_key)
                    direction = self._safer_turn(clearance, steps)
                    duration = 420
                    self._move(rover_url, api_key, direction, duration)
                    self._log(
                        f"step {steps + 1:03d}: obstacle {distance_cm:.0f} cm -> "
                        f"pivot {direction} {duration} ms "
                        f"(depth L/C/R {clearance['left']:.2f}/{clearance['center']:.2f}/{clearance['right']:.2f})",
                        "move",
                    )
                    self._set_status(action=direction, message=f"Avoiding obstacle at {distance_cm:.0f} cm")
                else:
                    side_best = max(clearance["left"], clearance["right"])
                    center_blocked = clearance["center"] < side_best * 0.72
                    if center_blocked:
                        direction = self._safer_turn(clearance, steps)
                        duration = 260
                        self._move(rover_url, api_key, direction, duration)
                        message = (
                            f"Depth steering {direction}; sonar {distance_cm:.0f} cm"
                            if distance_cm is not None
                            else f"Depth-only steering {direction}; sonar unavailable"
                        )
                    else:
                        direction = "forward"
                        duration = 300 if distance_cm is not None else 180
                        self._move(rover_url, api_key, direction, duration)
                        message = (
                            f"Path clear; sonar {distance_cm:.0f} cm"
                            if distance_cm is not None
                            else "Depth-only path clear; sonar unavailable"
                        )
                    self._log(
                        f"step {steps + 1:03d}: {message} -> {direction} {duration} ms "
                        f"(depth L/C/R {clearance['left']:.2f}/{clearance['center']:.2f}/{clearance['right']:.2f})",
                        "move",
                    )
                    self._set_status(action=direction, message=message)

                with self._lock:
                    self._steps += 1
                self._stop_event.wait(0.38)
        except Exception as exc:
            self._send_stop(rover_url, api_key)
            self._log(f"AUTONOMY ERROR: {exc}", "error")
            self._set_status(state="error", action="stopped", message=str(exc))
        finally:
            self._send_stop(rover_url, api_key)
            self._log("Exploration ended; final motor stop sent")

    def _run_find(self) -> None:
        with self._lock:
            rover_url = self._rover_url
            api_key = self._api_key
        if not rover_url:
            return

        last_llama_at = 0.0
        cached_llama: dict[str, Any] | None = None
        try:
            while not self._stop_event.is_set():
                with self._lock:
                    steps = self._steps
                if steps >= 60:
                    self._send_stop(rover_url, api_key)
                    self._log("Search limit reached after 60 movement steps; stopping", "warning")
                    self._set_status(
                        state="not_found", action="stopped",
                        message=f"Stopped after 60 search steps without reaching {self._target}",
                    )
                    return
                snapshot = self.pipeline.autonomy_snapshot()
                if snapshot is None:
                    raise RuntimeError("Camera stream was lost")

                sensors = snapshot.get("sensors") or {}
                sonar_ok = bool(sensors.get("sonar_ok"))
                try:
                    distance_cm = float(sensors.get("distance_cm")) if sonar_ok else None
                except (TypeError, ValueError):
                    distance_cm = None
                if distance_cm is not None and distance_cm <= 30.0:
                    self._send_stop(rover_url, api_key)
                    self._log(f"SONAR HARD STOP: obstacle at {distance_cm:.0f} cm", "error")
                    self._set_status(
                        state="blocked", action="stopped",
                        message=f"Obstacle safety stop at {distance_cm:.0f} cm",
                    )
                    return

                detection = self._semantic_detection(snapshot)
                now = time.monotonic()
                if detection is None and self._use_llama and now - last_llama_at >= 2.0:
                    self._send_stop(rover_url, api_key)
                    self._set_status(action="thinking", message=f"{self._model} is looking for {self._target}")
                    try:
                        cached_llama = self._llama_detection(snapshot)
                        last_llama_at = time.monotonic()
                    except RuntimeError as exc:
                        cached_llama = None
                        # A cold 12B model can be slow. Keep the rover safe, continue
                        # the deterministic scan, and retry vision after a cooldown.
                        last_llama_at = time.monotonic() + 8.0
                        self._log(f"Vision fallback unavailable; continuing YOLOE scan: {exc}", "warning")
                if detection is None:
                    detection = cached_llama

                if detection is None:
                    self._move(rover_url, api_key, "left", 220)
                    self._log(f"step {steps + 1:02d}: target not visible -> scan left for 220 ms", "move")
                    self._set_status(action="scan_left", message=f"Scanning for {self._target}")
                else:
                    center_x = float(detection["center_x"])
                    target_height = float(detection["height"])
                    if target_height >= 0.55 or (
                        distance_cm is not None and distance_cm <= 45.0 and 0.40 <= center_x <= 0.60
                    ):
                        self._send_stop(rover_url, api_key)
                        self._log(
                            f"ARRIVED: {detection['label']} via {detection['source']} "
                            f"(image height {target_height:.2f}, sonar {distance_cm if distance_cm is not None else 'n/a'} cm)",
                            "success",
                        )
                        self._set_status(
                            state="arrived", action="stopped",
                            message=f"Arrived at {detection['label']}", detection=detection,
                        )
                        return
                    if center_x < 0.40:
                        direction, duration = "left", 170
                    elif center_x > 0.60:
                        direction, duration = "right", 170
                    else:
                        direction, duration = "forward", 260
                    self._move(rover_url, api_key, direction, duration)
                    self._log(
                        f"step {steps + 1:02d}: {detection['source']} sees {detection['label']} "
                        f"at x={center_x:.2f}, height={target_height:.2f} -> {direction} for {duration} ms",
                        "move",
                    )
                    self._set_status(
                        action=direction,
                        message=f"Tracking {detection['label']} ({detection['source']})",
                        detection=detection,
                    )
                    if detection.get("source") == "ollama":
                        cached_llama = None

                with self._lock:
                    self._steps += 1
                self._stop_event.wait(0.35)
        except Exception as exc:
            self._send_stop(rover_url, api_key)
            self._log(f"AUTONOMY ERROR: {exc}", "error")
            self._set_status(state="error", action="stopped", message=str(exc))
        finally:
            self._send_stop(rover_url, api_key)
            self._log("Search loop ended; final motor stop sent")
