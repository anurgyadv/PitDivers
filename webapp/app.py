from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
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


STATIC_DIR = Path(__file__).resolve().parent / "static"


class ConnectRequest(BaseModel):
    stream_url: str
    model_id: str = "depth-anything/DA3-BASE"
    process_res: int = Field(default=504, ge=280, le=1008)
    inference_fps: float = Field(default=10.0, gt=0, le=30)
    depth_enabled: bool = True


class DepthToggleRequest(BaseModel):
    enabled: bool


class RecordRequest(BaseModel):
    name: str = ""
    keyframe_fps: float = Field(default=2.0, gt=0, le=15)
    stable_only: bool = False


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


@asynccontextmanager
async def lifespan(_: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    yield
    live_pipeline.disconnect()
    reconstruction_jobs.shutdown()


app = FastAPI(title="PitDivers Rover Vision", version="1.0.0", lifespan=lifespan)


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


@app.get("/api/live/status")
def live_status() -> dict:
    return live_pipeline.status()


@app.get("/api/sensors")
def sensor_readings() -> dict:
    """Proxy the ESP32 sensor API so the browser only talks to this dashboard."""
    stream_url = live_pipeline.status().get("stream_url", "")
    parsed = urlparse(stream_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return {"ok": False, "error": "Connect the camera to locate its sensor service"}

    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    sensor_url = f"{parsed.scheme}://{host}:82/sensors"
    request = Request(sensor_url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
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
    try:
        live_pipeline.connect(
            request.stream_url,
            request.model_id,
            request.process_res,
            request.inference_fps,
            request.depth_enabled,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return live_pipeline.status()


@app.post("/api/live/disconnect")
def disconnect() -> dict:
    live_pipeline.disconnect()
    return live_pipeline.status()


@app.post("/api/live/depth")
def set_depth(request: DepthToggleRequest) -> dict:
    """Turn the live DA3 depth view on or off without disconnecting."""
    live_pipeline.set_depth_enabled(request.enabled)
    return live_pipeline.status()


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


@app.get("/api/captures")
def captures() -> list[dict]:
    return list_captures()


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


@app.post("/api/models/download")
def download_model(request: ModelRequest) -> dict:
    try:
        model_downloads.start(request.model_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/{full_path:path}")
def frontend(full_path: str) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
