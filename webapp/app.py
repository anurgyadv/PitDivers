from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, Query, Request as FastAPIRequest, Header
from fastapi.responses import FileResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .core import (
    DATA_DIR,
    IMAGE_EXTENSIONS,
    ROOT_DIR,
    RUNS_DIR,
    image_files,
    list_captures,
    list_runs,
    live_pipeline,
    model_downloads,
    path_in,
    reconstruction_jobs,
    rename_run,
)
from .vio import rover_service_url
from .missions import MapStore, RoverMap, compile_plan, validate_map
from .semantic import SemanticStore
from .autonomy import AutonomyController, ollama_models
from .gamepad import GamepadBridgeManager
from .inspection_report import build_report, attach_remote_model, saved_rooms, REPORT_DIR
from .remote_da3 import remote_config, require_token, send_capture, import_capture, remote_job, MAX_UPLOAD_BYTES
from .sensor_esp import combine as combine_sensor_readings
from .rover_control import (
    RoverControlError,
    normalize_rover_url,
    rover_command_lock,
    rover_request,
    corrected_drive_request,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"
ROOM_UI_DIR = ROOT_DIR / "mapping"
ROOM_DEMO_URL = "http://127.0.0.1:8768"
ROOM_MAP_URL = "http://127.0.0.1:8767"
map_store = MapStore(DATA_DIR / "maps")
semantic_store = SemanticStore()
gamepad_bridge = GamepadBridgeManager(
    ROOT_DIR / "firmware" / "SKETCHES" / "rover_gamepad_bridge.ps1"
)
autonomy = AutonomyController(live_pipeline)


class ConnectRequest(BaseModel):
    stream_url: str
    sensor_base_url: str = "http://192.168.0.99"
    model_id: str = "depth-anything/DA3-BASE"
    process_res: int = Field(default=504, ge=280, le=1008)
    inference_fps: float = Field(default=10.0, gt=0, le=30)
    depth_enabled: bool = True
    semantic_enabled: bool = False
    semantic_fps: float = Field(default=1.0, gt=0, le=10)
    camera_profile: str = Field(default="quality", pattern="^(quality|vio)$")
    low_light_mode: str = Field(default="off", pattern="^(off|fast|ai)$")
    low_light_strength: int = Field(default=55, ge=0, le=100)
    rotation: int = Field(default=180)


class RecordRequest(BaseModel):
    name: str = ""
    keyframe_fps: float = Field(default=2.0, gt=0, le=15)
    stable_only: bool = False


class LowLightRequest(BaseModel):
    mode: str = Field(pattern="^(off|fast|ai)$")
    strength: int = Field(default=55, ge=0, le=100)


class ReconstructionRequest(BaseModel):
    capture_name: str
    model_id: str = "depth-anything/DA3-BASE"
    process_res: int = Field(default=504, ge=280, le=1008)
    conf_thresh_percentile: float = Field(default=55.0, ge=0, le=95)
    num_max_points: int = Field(default=1_000_000, ge=100_000, le=8_000_000)
    show_cameras: bool = False
    frames: list[str] | None = None


class RenameRunRequest(BaseModel):
    new_name: str


class ModelRequest(BaseModel):
    model_id: str


class InspectionReportRequest(BaseModel):
    capture_name: str
    room_id: str
    asset: str = Field(min_length=1, max_length=120)
    notes: str = Field(default="", max_length=4000)
    use_ai: bool = False
    model: str = Field(default="", max_length=120)
    openrouter_api_key: str = Field(default="", max_length=300)


class RemoteDa3ConfigRequest(BaseModel):
    url: str
    token: str


class RoverRequest(BaseModel):
    base_url: str


class RoverCommandRequest(RoverRequest):
    command: str = Field(pattern="^(forward|backward|left|right|stop)$")
    speed: int = Field(default=180, ge=80, le=255)


class GamepadStartRequest(RoverRequest):
    api_key: str = Field(min_length=1, max_length=200)
    max_speed: int = Field(default=180, ge=60, le=255)


class AutonomyStartRequest(RoverRequest):
    api_key: str = Field(min_length=1, max_length=200)
    mission: str = Field(default="explore", pattern="^(explore|find)$")
    target: str = Field(min_length=1, max_length=120)
    speed: int = Field(default=180, ge=60, le=220)
    use_llama: bool = False
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = Field(default="llama3.2-vision:11b", min_length=1, max_length=120)


class SemanticReviewRequest(BaseModel):
    status: str = "candidate"
    label: str
    note: str = ""


class SemanticCalibrationRequest(BaseModel):
    object_id: str
    axis: int = Field(ge=0, le=2)
    known_extent_m: float = Field(gt=0, le=1000)


class SemanticMergeRequest(BaseModel):
    object_ids: list[str] = Field(min_length=2)
    label: str = ""


class SemanticSplitRequest(BaseModel):
    axis: int = Field(ge=0, le=2)


@asynccontextmanager
async def lifespan(_: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    yield
    autonomy.stop()
    gamepad_bridge.stop()
    live_pipeline.disconnect()
    reconstruction_jobs.shutdown()


app = FastAPI(title="PitDivers Rover Vision", version="1.1.0", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    try:
        import torch

        cuda = torch.cuda.is_available()
        gpu = torch.cuda.get_device_name(0) if cuda else None
    except Exception:
        cuda = False
        gpu = None
    return {"ok": True, "cuda": cuda, "gpu": gpu}


@app.get("/api/rover/status")
def rover_status(base_url: str = Query(min_length=1)) -> dict:
    try:
        payload = rover_request(base_url, "/api/status")
        payload["base_url"] = normalize_rover_url(base_url)
        return payload
    except (ValueError, RoverControlError) as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/rover/connect")
def rover_connect(request: RoverRequest) -> dict:
    """Connect either signed-wheel firmware or the legacy motion ESP."""
    try:
        autonomy.stop()
        gamepad_bridge.stop()
        try:
            capabilities = rover_request(request.base_url, "/api/capabilities")
        except RoverControlError:
            capabilities = {}
        if not capabilities.get("signed_wheels"):
            try:
                rover_request(request.base_url, "/mode", method="POST", params={"value": "human"})
            except RoverControlError:
                # Some combined firmware lacks both optional endpoints.
                pass
        payload = rover_request(request.base_url, "/api/status")
        payload["base_url"] = normalize_rover_url(request.base_url)
        return payload
    except (ValueError, RoverControlError) as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/rover/command")
def rover_command(request: RoverCommandRequest) -> dict:
    try:
        with rover_command_lock:
            payload = corrected_drive_request(request.base_url, request.command, request.speed)
        return {"ok": True, "command": request.command, "speed": request.speed, **payload}
    except (ValueError, RoverControlError) as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/gamepad/status")
def gamepad_status() -> dict:
    return gamepad_bridge.status()


@app.post("/api/gamepad/start")
def gamepad_start(request: GamepadStartRequest) -> dict:
    try:
        autonomy.stop()
        return gamepad_bridge.start(request.base_url, request.api_key, request.max_speed)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/gamepad/stop")
def gamepad_stop() -> dict:
    return gamepad_bridge.stop()


@app.get("/api/autonomy/status")
def autonomy_status() -> dict:
    return autonomy.status()


@app.get("/api/autonomy/models")
def autonomy_models(ollama_url: str = Query(default="http://127.0.0.1:11434")) -> dict:
    try:
        return {"ok": True, "models": ollama_models(ollama_url)}
    except (ValueError, RuntimeError) as exc:
        return {"ok": False, "models": [], "error": str(exc)}


@app.post("/api/autonomy/start")
def autonomy_start(request: AutonomyStartRequest) -> dict:
    try:
        gamepad_bridge.stop()
        return autonomy.start(
            rover_url=request.base_url,
            api_key=request.api_key,
            mission=request.mission,
            target=request.target,
            speed=request.speed,
            use_llama=request.use_llama,
            ollama_url=request.ollama_url,
            model=request.model,
        )
    except (ValueError, RuntimeError, RoverControlError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/autonomy/stop")
def autonomy_stop() -> dict:
    return autonomy.stop()


@app.get("/api/live/status")
def live_status() -> dict:
    return live_pipeline.status()


@app.get("/api/sensors")
def sensor_readings(base_url: str = "http://192.168.0.99") -> dict:
    """Proxy the ESP32 sensor API so the browser only talks to this dashboard."""
    cached = live_pipeline.sensor_snapshot()
    if cached is not None and base_url.rstrip("/") == live_pipeline.sensor_base_url:
        cached["url"] = f"{live_pipeline.sensor_base_url}/api/environment"
        return cached

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"}:
        return {"ok": False, "error": "Enter a valid sensor ESP URL"}

    sensor_url = f"{base_url.rstrip('/')}/api/environment"
    request = Request(sensor_url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=1.5) as response:
            environment = json.loads(response.read().decode("utf-8"))
        try:
            with urlopen(Request(f"{base_url.rstrip('/')}/api/imu", headers={"Accept": "application/json"}), timeout=1.5) as response:
                imu = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
            imu = None
        payload = combine_sensor_readings(environment, imu)
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"ok": False, "error": f"Sensor returned HTTP {exc.code}"}
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"Sensor service unavailable: {exc}"}

    payload["url"] = sensor_url
    live_pipeline.update_sensor_snapshot(payload)
    return payload


@app.post("/api/live/connect")
def connect(request: ConnectRequest) -> dict:
    parsed = urlparse(request.stream_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "Enter a valid HTTP camera stream URL")
    sensor = urlparse(request.sensor_base_url)
    if sensor.scheme not in {"http", "https"} or not sensor.hostname or sensor.username or sensor.password or sensor.path not in {"", "/"}:
        raise HTTPException(400, "Enter a valid sensor ESP base URL")
    try:
        live_pipeline.connect(
            request.stream_url,
            request.model_id,
            request.process_res,
            request.inference_fps,
            request.depth_enabled,
            request.camera_profile,
            request.semantic_enabled,
            request.semantic_fps,
            request.low_light_mode,
            request.low_light_strength,
            request.rotation,
            request.sensor_base_url,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return live_pipeline.status()


@app.post("/api/live/disconnect")
def disconnect() -> dict:
    live_pipeline.disconnect()
    return live_pipeline.status()


@app.post("/api/live/enhancement")
def set_live_enhancement(request: LowLightRequest) -> dict:
    return live_pipeline.set_low_light(request.mode, request.strength)


@app.post("/api/live/record/start")
def record_start(request: RecordRequest) -> dict:
    try:
        name = live_pipeline.start_recording(
            request.name, request.keyframe_fps, request.stable_only
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"name": name, "status": live_pipeline.status()}


@app.post("/api/live/record/stop")
def record_stop() -> dict:
    manifest = live_pipeline.stop_recording()
    return {"manifest": manifest, "status": live_pipeline.status()}


@app.get("/api/live/raw.mjpg")
def raw_stream() -> StreamingResponse:
    return StreamingResponse(
        live_pipeline.mjpeg("raw"),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/live/depth.mjpg")
def depth_stream() -> StreamingResponse:
    return StreamingResponse(
        live_pipeline.mjpeg("depth"),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/live/original.mjpg")
def original_stream() -> StreamingResponse:
    return StreamingResponse(
        live_pipeline.mjpeg("original"),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/live/semantic.mjpg")
def semantic_stream() -> StreamingResponse:
    return StreamingResponse(
        live_pipeline.mjpeg("semantic"),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/captures")
def captures() -> list[dict]:
    return list_captures()


@app.get("/api/captures/{capture_name}/video")
def capture_video(capture_name: str) -> FileResponse:
    try:
        folder = path_in(DATA_DIR, capture_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    video = folder / "video.mp4"
    if not video.is_file():
        raise HTTPException(404, "Video not found for this capture")
    return FileResponse(video, media_type="video/mp4")


@app.get("/api/captures/{capture_name}/photos")
def capture_photos(
    capture_name: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=120, ge=1, le=500),
) -> dict:
    try:
        folder = path_in(DATA_DIR, capture_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    photos = image_files(folder)
    page = photos[offset : offset + limit]
    return {
        "name": capture_name,
        "total": len(photos),
        "offset": offset,
        "photos": [
            {
                "name": photo.name,
                "url": f"/api/captures/{capture_name}/photos/{photo.name}",
            }
            for photo in page
        ],
    }


@app.get("/api/captures/{capture_name}/photos/{photo_name}")
def capture_photo(capture_name: str, photo_name: str) -> FileResponse:
    try:
        folder = path_in(DATA_DIR, capture_name)
        photo = path_in(folder, photo_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if photo.suffix.lower() not in IMAGE_EXTENSIONS or not photo.is_file():
        raise HTTPException(404, "Photo not found")
    return FileResponse(photo)


@app.get("/api/runs")
def runs() -> list[dict]:
    return list_runs()


@app.get("/api/runs/{run_name}/model")
def run_model(run_name: str, download: bool = False) -> FileResponse:
    try:
        model = path_in(path_in(RUNS_DIR, run_name), "scene.glb")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not model.is_file():
        raise HTTPException(404, "3D model not found")
    return FileResponse(
        model,
        media_type="model/gltf-binary",
        filename=f"{run_name}.glb" if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


@app.get("/api/runs/{run_name}/thumbnail")
def run_thumbnail(run_name: str) -> FileResponse:
    try:
        image = path_in(path_in(RUNS_DIR, run_name), "scene.jpg")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not image.is_file():
        raise HTTPException(404, "Thumbnail not found")
    return FileResponse(image)


def _semantic_run_folder(run_name: str) -> Path:
    try:
        folder = path_in(RUNS_DIR, run_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not (folder / "objects.json").is_file():
        raise HTTPException(404, "Semantic object registry not found")
    return folder


@app.post("/api/runs/{run_name}/semantic/review/{object_id}")
def review_semantic_object(run_name: str, object_id: str, request: SemanticReviewRequest) -> dict:
    try:
        return semantic_store.review(_semantic_run_folder(run_name), object_id, status=request.status, label=request.label, note=request.note)
    except KeyError as exc:
        raise HTTPException(404, "Semantic object not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/runs/{run_name}/semantic/calibrate")
def calibrate_semantic_run(run_name: str, request: SemanticCalibrationRequest) -> dict:
    try:
        return semantic_store.calibrate(_semantic_run_folder(run_name), request.object_id, request.axis, request.known_extent_m)
    except KeyError as exc:
        raise HTTPException(404, "Semantic object not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/runs/{run_name}/semantic/merge")
def merge_semantic_objects(run_name: str, request: SemanticMergeRequest) -> dict:
    try:
        return semantic_store.merge(_semantic_run_folder(run_name), request.object_ids, request.label)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/runs/{run_name}/semantic/split/{object_id}")
def split_semantic_object(run_name: str, object_id: str, request: SemanticSplitRequest) -> dict:
    try:
        children = semantic_store.split(_semantic_run_folder(run_name), object_id, request.axis)
        return {"objects": children}
    except KeyError as exc:
        raise HTTPException(404, "Semantic object not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/runs/{run_name}/semantic/{asset_path:path}")
def run_semantic_asset(run_name: str, asset_path: str) -> FileResponse:
    """Serve semantic registries, reports, masks, and debug evidence from one run."""
    try:
        folder = path_in(RUNS_DIR, run_name)
        asset = (folder / asset_path).resolve()
        if not asset.is_relative_to(folder.resolve()):
            raise ValueError("Invalid path")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not asset.is_file():
        raise HTTPException(404, "Semantic asset not found")
    return FileResponse(asset)


@app.get("/api/jobs")
def jobs() -> dict:
    return reconstruction_jobs.status()


@app.post("/api/jobs/reconstruct")
def reconstruct(request: ReconstructionRequest) -> dict:
    live = live_pipeline.status()
    if live["state"] != "disconnected":
        raise HTTPException(
            409,
            "Disconnect Live mode before reconstruction so both processes do not compete for GPU memory",
        )
    try:
        return reconstruction_jobs.start(
            request.capture_name,
            request.model_id,
            request.process_res,
            request.conf_thresh_percentile,
            request.num_max_points,
            request.show_cameras,
            request.frames,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    try:
        reconstruction_jobs.cancel(job_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return reconstruction_jobs.status()


@app.post("/api/jobs/{job_id}/dismiss")
def dismiss_job(job_id: str) -> dict:
    try:
        reconstruction_jobs.dismiss(job_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return reconstruction_jobs.status()


@app.post("/api/runs/{run_name}/rename")
def rename_run_endpoint(run_name: str, request: RenameRunRequest) -> dict:
    try:
        final = rename_run(run_name, request.new_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"name": final}


@app.get("/api/models")
def models() -> list[dict]:
    return model_downloads.models()


@app.get("/api/inspection/rooms")
def inspection_rooms() -> list[dict]:
    return saved_rooms()


@app.get("/api/remote/da3/config")
def remote_da3_config() -> dict:
    return remote_config()


@app.post("/api/remote/da3/config")
def set_remote_da3_config(request: RemoteDa3ConfigRequest) -> dict:
    url = request.url.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".ts.net") or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise HTTPException(400, "Enter the PC's HTTPS Tailscale Serve URL")
    if len(request.token.strip()) < 16:
        raise HTTPException(400, "The shared DA3 token must be at least 16 characters")
    os.environ["PITDIVERS_DA3_REMOTE_URL"] = url
    os.environ["PITDIVERS_REMOTE_TOKEN"] = request.token.strip()
    return remote_config()


@app.post("/api/remote/da3/send/{capture_name}")
def remote_da3_send(capture_name: str) -> dict:
    try:
        return send_capture(capture_name)
    except (ValueError, FileNotFoundError, URLError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/remote/da3/status/{capture_name}")
def remote_da3_status(capture_name: str) -> dict:
    try:
        return remote_job(capture_name)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/remote/da3/import/{capture_name}")
async def remote_da3_import(capture_name: str, request: FastAPIRequest, x_pitdivers_token: str | None = Header(default=None)) -> dict:
    try:
        require_token(x_pitdivers_token)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    if int(request.headers.get("content-length", "0")) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Capture upload exceeds 512 MB")
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Capture upload exceeds 512 MB")
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        folder_name = import_capture(capture_name, body)
        if live_pipeline.status()["state"] != "disconnected":
            raise RuntimeError("Disconnect live DA3 on the processing PC before starting reconstruction")
        job = reconstruction_jobs.start(folder_name, "depth-anything/DA3-BASE", 504)
        return {"capture": folder_name, "job": job}
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/remote/da3/jobs/{job_id}")
def remote_da3_job(job_id: str, x_pitdivers_token: str | None = Header(default=None)) -> dict:
    try:
        require_token(x_pitdivers_token)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    item = next((job for job in reconstruction_jobs.status()["jobs"] if job["id"] == job_id), None)
    if item is None:
        raise HTTPException(404, "DA3 job not found")
    return {"id": item["id"], "state": item["state"], "stage": item.get("stage"),
            "error": item.get("error"), "run_name": item.get("run_name")}


@app.get("/room-demo/")
def room_demo_page() -> Response:
    page = (ROOM_UI_DIR / "demo.html").read_text(encoding="utf-8")
    for script in ("demo.js", "gamepad.js", "calibration.js"):
        page = page.replace(f'src="/{script}"', f'src="/room-demo/{script}"')
    return Response(page, media_type="text/html")


@app.get("/room-demo/{script_name}")
def room_demo_script(script_name: str) -> Response:
    if script_name not in {"demo.js", "gamepad.js", "calibration.js"}:
        raise HTTPException(404, "Room UI script not found")
    script = (ROOM_UI_DIR / script_name).read_text(encoding="utf-8")
    return Response(script.replace("/api/", "/room-demo/api/"), media_type="text/javascript")


ROOM_GET_PATHS = {"state", "calibration"}
ROOM_POST_PATHS = {"scan", "finish", "plan", "go", "stop", "drive", "calibration/start", "calibration/heartbeat"}


def _room_request(path: str, body: bytes | None = None) -> Response:
    request = Request(f"{ROOM_DEMO_URL}/api/{path}", data=body,
                      headers={"Content-Type": "application/json"} if body is not None else {},
                      method="POST" if body is not None else "GET")
    try:
        with urlopen(request, timeout=30 if path in {"scan", "finish"} else 5) as upstream:
            return Response(upstream.read(), media_type="application/json", status_code=upstream.status)
    except HTTPError as exc:
        return Response(exc.read(), media_type="application/json", status_code=exc.code)
    except (URLError, TimeoutError, OSError) as exc:
        raise HTTPException(503, "Room mapping service is unavailable. Start mapping/start_demo.ps1 on the dashboard host.") from exc


@app.get("/room-demo/api/{path:path}")
def room_demo_get(path: str) -> Response:
    if path not in ROOM_GET_PATHS:
        raise HTTPException(404, "Room endpoint not found")
    return _room_request(path)


@app.post("/room-demo/api/{path:path}")
def room_demo_post(path: str, payload: dict) -> Response:
    if path not in ROOM_POST_PATHS:
        raise HTTPException(404, "Room endpoint not found")
    body = json.dumps(payload).encode("utf-8")
    if len(body) > 4096:
        raise HTTPException(413, "Room command too large")
    return _room_request(path, body)


def _expedition_map_request(path: str, body: dict | None = None) -> dict:
    request = Request(f"{ROOM_MAP_URL}/api/{path}",
                      data=json.dumps(body).encode("utf-8") if body is not None else None,
                      headers={"Content-Type": "application/json"} if body is not None else {},
                      method="POST" if body is not None else "GET")
    try:
        with urlopen(request, timeout=8) as response:
            return json.load(response)
    except HTTPError as exc:
        raise HTTPException(exc.code, exc.read(300).decode("utf-8", "replace")) from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise HTTPException(503, "LiDAR mapping service is unavailable") from exc


@app.get("/api/expedition/map")
def expedition_map() -> dict:
    return _expedition_map_request("state")


@app.post("/api/expedition/lidar/{action}")
def expedition_lidar(action: str) -> dict:
    if action not in {"start", "stop"}:
        raise HTTPException(400, "Invalid LiDAR action")
    return _expedition_map_request("lidar", {"action": action})


@app.post("/api/expedition/map/save")
def expedition_save_map() -> dict:
    _expedition_map_request("save", {})
    state = _expedition_map_request("state")
    return {"room_id": state.get("run_id"), "saved": True}


@app.get("/api/inspection/reports")
def inspection_reports() -> list[dict]:
    reports = []
    for file in REPORT_DIR.glob("*/report.json"):
        try:
            item = json.loads(file.read_text(encoding="utf-8"))
            if item.get("test_only"):
                continue
            item["html_url"] = f"/api/inspection/reports/{file.parent.name}/report.html"
            reports.append(item)
        except (OSError, ValueError):
            continue
    return sorted(reports, key=lambda item: item.get("created_at", ""), reverse=True)


@app.post("/api/inspection/reports")
def create_inspection_report(request: InspectionReportRequest) -> dict:
    try:
        return build_report(request.capture_name, request.room_id, request.asset,
                            request.notes, request.use_ai, request.model, request.openrouter_api_key)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/inspection/reports/{report_id}/attach-model")
def attach_inspection_model(report_id: str) -> dict:
    try:
        return attach_remote_model(report_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/inspection/reports/{report_id}/{filename}")
def inspection_report_file(report_id: str, filename: str) -> FileResponse:
    if filename not in {"report.html", "report.pdf", "model-viewer.min.js", "scene.glb", "video.mp4", "map.svg", "temperature.svg", "humidity.svg", "source.json", "frames.json", "sensors.jsonl", "report.json"}:
        raise HTTPException(404, "Evidence file not found")
    try:
        folder = path_in(REPORT_DIR, report_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    file = folder / filename
    if not file.is_file():
        raise HTTPException(404, "Evidence file not found")
    return FileResponse(file, media_type="model/gltf-binary" if filename == "scene.glb" else None)


@app.post("/api/models/download")
def download_model(request: ModelRequest) -> dict:
    try:
        model_downloads.start(request.model_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@app.get("/api/maps")
def maps() -> list[dict]:
    return map_store.list()


@app.get("/api/maps/{map_id}")
def get_map(map_id: str) -> dict:
    try:
        rover_map = map_store.get(map_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "Map not found") from exc
    return rover_map.model_dump(mode="json")


@app.post("/api/maps")
def create_map(rover_map: RoverMap) -> dict:
    saved = map_store.save(rover_map)
    return {
        "map": saved.model_dump(mode="json"),
        "validation": validate_map(saved),
    }


@app.put("/api/maps/{map_id}")
def update_map(map_id: str, rover_map: RoverMap) -> dict:
    try:
        saved = map_store.save(rover_map, requested_id=map_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "map": saved.model_dump(mode="json"),
        "validation": validate_map(saved),
    }


@app.post("/api/maps/validate")
def validate_map_endpoint(rover_map: RoverMap) -> dict:
    return validate_map(rover_map)


@app.post("/api/maps/plan")
def compile_map_plan(rover_map: RoverMap) -> dict:
    try:
        return compile_plan(rover_map)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/{full_path:path}")
def frontend(full_path: str) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
