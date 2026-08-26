from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import cv2


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
RUNS_DIR = ROOT_DIR / "runs"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


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


class LivePipeline:
    """Own the ESP32 capture, live DA3 inference, and keyframe recording."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._model_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._inference_thread: threading.Thread | None = None
        self._capture: cv2.VideoCapture | None = None
        self._model: Any = None
        self._generation = 0

        self.stream_url = "http://192.168.0.69:81/stream"
        self.model_id = "depth-anything/DA3-BASE"
        self.process_res = 504
        self.inference_fps = 5.0
        self.state = "disconnected"
        self.model_state = "idle"
        self.error: str | None = None
        self.connected_at: str | None = None

        self._latest_frame: Any = None
        self._raw_jpeg: bytes | None = None
        self._depth_jpeg: bytes | None = None
        self._raw_sequence = 0
        self._depth_sequence = 0
        self._frame_width = 0
        self._frame_height = 0
        self._capture_fps = 0.0
        self._depth_fps = 0.0
        self._last_inference_ms = 0.0

        self._recording = False
        self._recording_name: str | None = None
        self._recording_dir: Path | None = None
        self._recording_started_at: str | None = None
        self._keyframe_fps = 2.0
        self._keyframe_count = 0
        self._last_keyframe_at = 0.0

    def connect(self, stream_url: str, model_id: str, process_res: int, inference_fps: float) -> None:
        self.disconnect()
        with self._lock:
            self._generation += 1
            generation = self._generation
            self.stream_url = stream_url
            self.model_id = model_id
            self.process_res = process_res
            self.inference_fps = inference_fps
            self.state = "connecting"
            self.model_state = "loading"
            self.error = None
            self.connected_at = utc_now()
            self._latest_frame = None
            self._raw_jpeg = None
            self._depth_jpeg = None
            self._raw_sequence = 0
            self._depth_sequence = 0
            self._capture_fps = 0.0
            self._depth_fps = 0.0
            self._last_inference_ms = 0.0
            self._frame_width = 0
            self._frame_height = 0
            self._stop_event = threading.Event()

        self._capture_thread = threading.Thread(
            target=self._capture_loop, args=(generation,), daemon=True, name="rover-capture"
        )
        self._inference_thread = threading.Thread(
            target=self._inference_loop, args=(generation,), daemon=True, name="da3-live"
        )
        self._capture_thread.start()
        self._inference_thread.start()

    def disconnect(self) -> None:
        self.stop_recording()
        self._stop_event.set()
        capture = self._capture
        if capture is not None:
            capture.release()
        for thread in (self._capture_thread, self._inference_thread):
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=3.0)
        with self._model_lock:
            self._model = None
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
            self.state = "disconnected"
            self.model_state = "idle"
            self.connected_at = None

    def _capture_loop(self, generation: int) -> None:
        frame_counter = 0
        counter_started = time.perf_counter()
        reconnects = 0
        while not self._stop_event.is_set() and generation == self._generation:
            capture = cv2.VideoCapture(self.stream_url)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not capture.isOpened():
                capture.release()
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

            while not self._stop_event.is_set() and generation == self._generation:
                ok, frame = capture.read()
                if not ok:
                    with self._lock:
                        self.state = "reconnecting"
                        self.error = "Camera stream interrupted; reconnecting"
                    break

                encoded_ok, encoded = cv2.imencode(
                    ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88]
                )
                if not encoded_ok:
                    continue
                now = time.perf_counter()
                frame_counter += 1
                elapsed = now - counter_started
                if elapsed >= 1.0:
                    with self._lock:
                        self._capture_fps = frame_counter / elapsed
                    frame_counter = 0
                    counter_started = now

                with self._lock:
                    self._latest_frame = frame.copy()
                    self._raw_jpeg = encoded.tobytes()
                    self._raw_sequence += 1
                    self._frame_height, self._frame_width = frame.shape[:2]
                    should_save = (
                        self._recording
                        and self._recording_dir is not None
                        and now - self._last_keyframe_at >= 1.0 / self._keyframe_fps
                    )
                    record_dir = self._recording_dir
                    frame_number = self._keyframe_count

                if should_save and record_dir is not None:
                    output = record_dir / f"frame_{frame_number:06d}.jpg"
                    if cv2.imwrite(
                        str(output), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95]
                    ):
                        with self._lock:
                            self._keyframe_count += 1
                            self._last_keyframe_at = now

            capture.release()
            with self._lock:
                if self._capture is capture:
                    self._capture = None
            self._stop_event.wait(0.25)

    def _inference_loop(self, generation: int) -> None:
        try:
            import torch
            from depth_anything_3.api import DepthAnything3
            from depth_anything_3.utils.visualize import visualize_depth

            if not torch.cuda.is_available():
                raise RuntimeError("CUDA is unavailable. Live DA3 requires the NVIDIA GPU.")

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
                prediction = model.inference(
                    [rgb_frame],
                    process_res=self.process_res,
                    process_res_method="upper_bound_resize",
                )
                depth_rgb = visualize_depth(prediction.depth[0])
                depth_bgr = cv2.cvtColor(depth_rgb, cv2.COLOR_RGB2BGR)
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

    def start_recording(self, requested_name: str, keyframe_fps: float) -> str:
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

        with self._lock:
            self._recording = True
            self._recording_name = name
            self._recording_dir = folder
            self._recording_started_at = utc_now()
            self._keyframe_fps = keyframe_fps
            self._keyframe_count = 0
            self._last_keyframe_at = 0.0
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
        write_json(folder / "capture.json", manifest)
        return manifest

    def _manifest(self, state: str) -> dict[str, Any]:
        return {
            "name": self._recording_name,
            "state": state,
            "started_at": self._recording_started_at,
            "stream_url": self.stream_url,
            "model_id": self.model_id,
            "process_res": self.process_res,
            "inference_fps": self.inference_fps,
            "keyframe_fps": self._keyframe_fps,
            "frames": self._keyframe_count,
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
                "model_id": self.model_id,
                "process_res": self.process_res,
                "inference_fps": self.inference_fps,
                "connected_at": self.connected_at,
                "capture_fps": round(self._capture_fps, 1),
                "depth_fps": round(self._depth_fps, 1),
                "inference_ms": round(self._last_inference_ms),
                "width": self._frame_width,
                "height": self._frame_height,
                "recording": self._recording,
                "recording_name": self._recording_name,
                "frames_saved": self._keyframe_count,
                "keyframe_fps": self._keyframe_fps,
            }

    def mjpeg(self, kind: str) -> Iterator[bytes]:
        last_sequence = -1
        while True:
            with self._lock:
                if kind == "depth":
                    payload = self._depth_jpeg
                    sequence = self._depth_sequence
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

    def start(self, capture_name: str, model_id: str, process_res: int) -> dict[str, Any]:
        if model_id not in MODEL_IDS:
            raise ValueError("Unknown model")
        capture_dir = path_in(DATA_DIR, capture_name)
        count = len(image_files(capture_dir))
        if count < 2:
            raise ValueError("At least two captured images are required")

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
            job["state"] = "running"
            job["stage"] = "Starting DA3"
            job["started_at"] = utc_now()

        command = [
            sys.executable,
            "-m",
            "depth_anything_3.cli",
            "images",
            str(capture_dir),
            "--model-dir",
            job["model_id"],
            "--export-format",
            "glb",
            "--export-dir",
            str(run_dir),
            "--process-res",
            str(job["process_res"]),
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

    def status(self) -> dict[str, Any]:
        with self._lock:
            jobs = sorted(
                (job.copy() for job in self._jobs.values()),
                key=lambda item: item["created_at"],
                reverse=True,
            )
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
        if not images:
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
            }
        )
    return sorted(runs, key=lambda item: item["updated_at"], reverse=True)
