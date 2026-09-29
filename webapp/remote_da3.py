"""Transfer a capture from the field laptop to a DA3 PC over a private URL."""
from __future__ import annotations

import hmac
import io
import json
import os
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import quote, urlparse

from .core import DATA_DIR, image_files, path_in, safe_slug


MAX_UPLOAD_BYTES = 512 * 1024 * 1024


def remote_config() -> dict:
    url = os.environ.get("PITDIVERS_DA3_REMOTE_URL", "").strip().rstrip("/")
    token = os.environ.get("PITDIVERS_REMOTE_TOKEN", "").strip()
    return {"configured": bool(url and token), "url": url}


def require_token(provided: str | None) -> None:
    expected = os.environ.get("PITDIVERS_REMOTE_TOKEN", "").strip()
    if not expected or not provided or not hmac.compare_digest(expected, provided):
        raise PermissionError("Remote DA3 token is missing or invalid")


def capture_package(name: str) -> bytes:
    folder = path_in(DATA_DIR, name)
    frames = image_files(folder)
    if len(frames) < 2:
        raise ValueError("Capture needs at least two frames")
    # DA3 is run on a bounded, evenly spaced subset to keep the tailnet upload practical.
    count = min(120, len(frames))
    indices = sorted(set(round(i * (len(frames) - 1) / (count - 1)) for i in range(count)))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for index in indices:
            frame = frames[index]
            archive.write(frame, frame.name)
            metadata = frame.with_suffix(".json")
            if metadata.is_file():
                archive.write(metadata, metadata.name)
        manifest = folder / "capture.json"
        if manifest.is_file():
            archive.write(manifest, "capture.json")
    if buffer.tell() > MAX_UPLOAD_BYTES:
        raise ValueError("Selected capture exceeds the 512 MB transfer limit")
    return buffer.getvalue()


def send_capture(name: str) -> dict:
    config = remote_config()
    if not config["configured"]:
        raise ValueError("Set PITDIVERS_DA3_REMOTE_URL and PITDIVERS_REMOTE_TOKEN on the laptop")
    parsed = urlparse(config["url"])
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".ts.net") or parsed.username or parsed.password or parsed.path or parsed.query:
        raise ValueError("Remote DA3 URL must be an HTTPS Tailscale Serve address")
    body = capture_package(name)
    request = urllib.request.Request(
        f"{config['url']}/api/remote/da3/import/{quote(name, safe='')}",
        data=body, method="POST",
        headers={"Content-Type": "application/zip", "X-PitDivers-Token": os.environ["PITDIVERS_REMOTE_TOKEN"]},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Remote DA3 returned HTTP {exc.code}: {exc.read(500).decode('utf-8', 'replace')}") from exc
    result["remote_url"] = config["url"]
    (path_in(DATA_DIR, name) / "remote_da3.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def remote_job(name: str) -> dict:
    folder = path_in(DATA_DIR, name)
    file = folder / "remote_da3.json"
    if not file.is_file():
        return {"state": "not_submitted"}
    saved = json.loads(file.read_text(encoding="utf-8"))
    job_id = saved["job"]["id"]
    config = remote_config()
    if not config["configured"]:
        return {"state": "unavailable", "error": "Remote DA3 configuration is missing"}
    request = urllib.request.Request(
        f"{config['url']}/api/remote/da3/jobs/{quote(job_id)}",
        headers={"X-PitDivers-Token": os.environ["PITDIVERS_REMOTE_TOKEN"]},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            item = json.load(response)
    except (OSError, ValueError) as exc:
        return {"state": "unavailable", "error": str(exc)}
    if item.get("state") == "complete" and item.get("run_name"):
        item["model_url"] = f"{config['url']}/api/runs/{quote(item['run_name'])}/model"
    file.write_text(json.dumps({**saved, "status": item}, indent=2), encoding="utf-8")
    return item


def import_capture(name: str, body: bytes) -> str:
    if not 0 < len(body) <= MAX_UPLOAD_BYTES:
        raise ValueError("Upload must be between 1 byte and 512 MB")
    folder_name = safe_slug("remote_" + name, "remote_capture")
    folder = path_in(DATA_DIR, folder_name)
    if folder.exists():
        suffix = 2
        while path_in(DATA_DIR, f"{folder_name}_{suffix}").exists():
            suffix += 1
        folder_name = f"{folder_name}_{suffix}"
        folder = path_in(DATA_DIR, folder_name)
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = archive.namelist()
        if len(names) > 260 or len(names) != len(set(names)) or sum(item.file_size for item in archive.infolist()) > MAX_UPLOAD_BYTES or not any(item.lower().endswith(".jpg") for item in names):
            raise ValueError("Archive must contain JPEG frames")
        for item in archive.infolist():
            if item.is_dir() or Path(item.filename).name != item.filename or item.file_size > 15 * 1024 * 1024:
                raise ValueError("Invalid capture archive entry")
            if Path(item.filename).suffix.lower() not in {".jpg", ".json"}:
                raise ValueError("Capture archive contains an unsupported file")
        folder.mkdir(parents=True)
        for item in archive.infolist():
            with archive.open(item) as source, (folder / item.filename).open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
    return folder_name
