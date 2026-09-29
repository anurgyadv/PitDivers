"""Build a reviewable inspection bundle from saved rover evidence."""
from __future__ import annotations

import base64
import html
import json
import math
import os
import shutil
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote

from PIL import Image, ImageDraw

from tools.render_room_report import render as render_room_layer
from .core import DATA_DIR, RUNS_DIR, image_files, path_in, safe_slug, list_runs


MAP_DIR = DATA_DIR / "lidar-maps"
REPORT_DIR = DATA_DIR / "reports"


def saved_rooms() -> list[dict]:
    rooms = []
    for file in MAP_DIR.glob("*.json"):
        if len(file.stem) != 12 or any(c not in "0123456789abcdef" for c in file.stem):
            continue
        rooms.append({"id": file.stem, "updated_at": datetime.fromtimestamp(file.stat().st_mtime, timezone.utc).isoformat()})
    return sorted(rooms, key=lambda item: item["updated_at"], reverse=True)


def _read_room(room_id: str) -> dict:
    if len(room_id) != 12 or any(c not in "0123456789abcdef" for c in room_id):
        raise ValueError("Choose a saved LiDAR room")
    file = MAP_DIR / f"{room_id}.json"
    if not file.is_file():
        raise FileNotFoundError("Saved LiDAR room not found")
    data = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(data.get("map"), dict) or not data["map"].get("cells"):
        raise ValueError("Saved room has no map cells")
    return data


def _frame_evidence(folder: Path) -> list[dict]:
    result = []
    for frame in image_files(folder):
        telemetry = frame.with_suffix(".json")
        try:
            meta = json.loads(telemetry.read_text(encoding="utf-8")) if telemetry.is_file() else {}
        except (OSError, ValueError):
            meta = {}
        result.append({"file": frame.name, "captured_at": meta.get("captured_at"), "sensors": meta.get("sensors") or {}})
    return result


def _numbers(frames: list[dict], field: str) -> list[float]:
    values = []
    for frame in frames:
        sensors = frame["sensors"]
        value = sensors.get(field)
        if sensors.get("dht_ok") is not False and isinstance(value, (int, float)) and math.isfinite(value):
            values.append(float(value))
    return values


def _sensor_evidence(folder: Path, frames: list[dict]) -> list[dict]:
    file = folder / "sensors.jsonl"
    if not file.is_file():
        return frames
    result = []
    with file.open(encoding="utf-8") as source:
        for line in source:
            try:
                item = json.loads(line)
                if isinstance(item.get("sensors"), dict):
                    result.append(item)
            except (ValueError, TypeError):
                continue
    return result or frames


def _stats(values: list[float], unit: str) -> str:
    if not values:
        return "No valid readings"
    return f"{min(values):.1f}–{max(values):.1f} {unit}; mean {sum(values) / len(values):.1f} {unit}; n={len(values)}"


def _association(room: dict, folder: Path) -> str:
    manifest_file = folder / "capture.json"
    if not manifest_file.is_file():
        return "Unverified: this capture has no timing manifest."
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        start = datetime.fromisoformat(manifest["started_at"].replace("Z", "+00:00")).timestamp()
        end = datetime.fromisoformat(manifest.get("completed_at", manifest["started_at"]).replace("Z", "+00:00")).timestamp()
        map_start = float(room["created"])
        map_end = float(room["saved_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return "Unverified: source timestamps are unavailable."
    if start <= map_end + 300 and end >= map_start - 300:
        return "Timestamps overlap within five minutes; operator must confirm the sources describe the same inspection."
    return "WARNING: map and camera capture timestamps do not overlap. Confirm the selected sources before using this report."


def _map_image(room: dict, destination: Path, field: int | None = None) -> None:
    cells = room["cells"]
    resolution = float(room["resolution"])
    if not cells or not math.isfinite(resolution) or resolution <= 0:
        raise ValueError("Invalid saved map resolution")
    xs = [int(c[0]) for c in cells]
    ys = [int(c[1]) for c in cells]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    width, height = 1000, 690
    scale = min(920 / max(1, max_x - min_x + 1), 600 / max(1, max_y - min_y + 1))
    image = Image.new("RGB", (width, height), "#f7f9fc")
    draw = ImageDraw.Draw(image)
    for x, y, occupancy in cells:
        px = 40 + (x - min_x) * scale
        py = 40 + (max_y - y) * scale
        colour = "#33465a" if occupancy == 8 else "#dce6ef" if occupancy == -8 else "#f1f4f7"
        draw.rectangle((px, py, px + max(1, scale), py + max(1, scale)), fill=colour)
    path = room.get("path") or []
    if len(path) > 1:
        points = [(40 + (p[0] / resolution - min_x) * scale,
                   40 + (max_y - p[1] / resolution) * scale) for p in path if len(p) >= 2]
        if len(points) > 1:
            draw.line(points, fill="#008675", width=3)
    if field is not None:
        samples = [p for p in room.get("environment", []) if len(p) >= 6 and
                   isinstance(p[field], (int, float)) and math.isfinite(p[field])]
        values = [p[field] for p in samples]
        low, high = (min(values), max(values)) if values else (0, 0)
        for p in samples:
            x = 40 + (p[0] / resolution - min_x) * scale
            y = 40 + (max_y - p[1] / resolution) * scale
            fraction = .5 if high == low else (p[field] - low) / (high - low)
            colour = (int(40 + 205 * fraction), int(150 - 65 * fraction), int(220 - 165 * fraction))
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=colour, outline="white", width=2)
        label = "Temperature (C)" if field == 2 else "Humidity (% RH)"
        draw.text((40, 650), f"{label}: {low:.1f} to {high:.1f} | {len(samples)} positioned samples", fill="#15283b")
    image.save(destination)


def _ai_observation(folder: Path, frames: list[dict], asset: str, notes: str, model: str, api_key: str = "") -> dict:
    key = api_key.strip() or os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return {"status": "unavailable", "text": "OPENROUTER_API_KEY is not configured on the dashboard host."}
    if not model or len(model) > 120:
        raise ValueError("Choose a valid OpenRouter vision model ID")
    chosen = [frames[i] for i in sorted(set(round(i * (len(frames) - 1) / min(5, len(frames) - 1)) for i in range(min(6, len(frames))))) ] if len(frames) > 1 else frames
    content = [{"type": "text", "text": (
        f"You are drafting a mining inspection observation for {asset}. Operator notes: {notes or 'None'}. "
        "Describe only visible evidence in these ordered frames. Produce a mining inspection draft with "
        "scene sequence, visible equipment and conditions, possible hazards requiring review, uncertainties, "
        "and recommended human checks. Cite the provided frame order when describing changes. "
        "Distinguish observations from possible explanations. Do not assert a machine fault, safety status, "
        "temperatures, or distances that the images do not establish. Use short plain-text section headings."
    )}]
    for item in chosen:
        raw = (folder / item["file"]).read_bytes()
        content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")}})
    payload = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 1200}
    request = Request("https://openrouter.ai/api/v1/chat/completions",
                      data=json.dumps(payload).encode("utf-8"),
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=90) as response:
            reply = json.load(response)
        text = reply["choices"][0]["message"]["content"]
        return {"status": "complete", "text": str(text)[:6000], "model": model,
                "frame_ids": [item["file"] for item in chosen], "usage": reply.get("usage")}
    except Exception as exc:
        return {"status": "unavailable", "text": f"AI analysis failed: {type(exc).__name__}"}


def build_report(capture_name: str, room_id: str, asset: str, notes: str,
                 use_ai: bool = False, model: str = "", api_key: str = "") -> dict:
    if not asset.strip():
        raise ValueError("Enter an asset or inspection area name")
    folder = path_in(DATA_DIR, capture_name)
    if not folder.is_dir():
        raise FileNotFoundError("Capture not found")
    frames = _frame_evidence(folder)
    sensors = _sensor_evidence(folder, frames)
    if not frames:
        raise ValueError("Capture contains no photos")
    room = _read_room(room_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_id = safe_slug(f"{stamp}_{asset}", "inspection")
    output = REPORT_DIR / report_id
    output.mkdir(parents=True, exist_ok=False)
    (output / "source.json").write_text(json.dumps(room, indent=2), encoding="utf-8")
    for name, field in (("map", None), ("temperature", 2), ("humidity", 3)):
        (output / f"{name}.svg").write_text(render_room_layer(room["map"], field), encoding="utf-8")
        _map_image(room["map"], output / f"{name}.png", field)
    ai = _ai_observation(folder, frames, asset, notes, model, api_key) if use_ai else {"status": "skipped", "text": "AI analysis was not requested."}
    remote_file = folder / "remote_da3.json"
    remote = json.loads(remote_file.read_text(encoding="utf-8")) if remote_file.is_file() else {}
    remote_model = remote.get("status", {}).get("model_url")
    local_model = next((r["name"] for r in list_runs() if r["name"].startswith(capture_name)), None)
    model_error = None
    if remote_model:
        try:
            from .remote_da3 import remote_config
            config = remote_config()
            if not config["configured"] or not remote_model.startswith(config["url"] + "/api/runs/") or not remote_model.endswith("/model"):
                raise ValueError("Remote model URL does not match the configured DA3 PC")
            with urlopen(Request(remote_model, headers={"X-PitDivers-Token": os.environ["PITDIVERS_REMOTE_TOKEN"]}), timeout=120) as source, (output / "scene.glb").open("wb") as target:
                size = 0
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    if size > 1024 * 1024 * 1024:
                        raise ValueError("DA3 model exceeds 1 GB")
                    target.write(chunk)
        except (OSError, ValueError) as exc:
            (output / "scene.glb").unlink(missing_ok=True)
            model_error = str(exc)
    elif local_model:
        source = path_in(path_in(RUNS_DIR, local_model), "scene.glb")
        if source.is_file():
            shutil.copyfile(source, output / "scene.glb")
    mapped = [p for p in room["map"].get("environment", []) if len(p) >= 6]
    record = {"id": report_id, "asset": asset.strip(), "notes": notes.strip(), "capture": capture_name,
              "room_id": room_id, "created_at": datetime.now(timezone.utc).isoformat(),
              "source_association": _association(room, folder),
              "frame_count": len(frames), "sensor_samples": len(sensors),
              "temperature": _stats(_numbers(sensors, "temperature_c"), "°C"),
              "humidity": _stats(_numbers(sensors, "humidity_percent"), "% RH"), "ai": ai,
              "mapped_temperature": _stats([float(p[2]) for p in mapped if isinstance(p[2], (int, float)) and math.isfinite(p[2])], "°C"),
              "mapped_humidity": _stats([float(p[3]) for p in mapped if isinstance(p[3], (int, float)) and math.isfinite(p[3])], "% RH"),
              "model": local_model, "remote_model_url": remote_model,
              "model_file": "scene.glb" if (output / "scene.glb").is_file() else None,
              "model_error": model_error,
              "video_url": f"/api/captures/{capture_name}/video" if (folder / "video.mp4").is_file() else None,
              "sensor_file": "sensors.jsonl" if (folder / "sensors.jsonl").is_file() else None}
    (output / "report.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    (output / "frames.json").write_text(json.dumps(frames, indent=2), encoding="utf-8")
    if (folder / "sensors.jsonl").is_file():
        shutil.copyfile(folder / "sensors.jsonl", output / "sensors.jsonl")
    if (folder / "video.mp4").is_file():
        shutil.copyfile(folder / "video.mp4", output / "video.mp4")
    shutil.copyfile(Path(__file__).parent / "static" / "vendor" / "model-viewer.min.js", output / "model-viewer.min.js")
    _html(output / "report.html", output, folder, frames, sensors, room, record)
    return record


def attach_remote_model(report_id: str) -> dict:
    """Refresh an existing report after its remote DA3 reconstruction finishes."""
    output = path_in(REPORT_DIR, report_id)
    metadata = output / "report.json"
    if not metadata.is_file():
        raise FileNotFoundError("Report not found")
    record = json.loads(metadata.read_text(encoding="utf-8"))
    capture = path_in(DATA_DIR, record["capture"])
    remote_file = capture / "remote_da3.json"
    remote = json.loads(remote_file.read_text(encoding="utf-8")) if remote_file.is_file() else {}
    remote_model = remote.get("status", {}).get("model_url")
    if not remote_model:
        raise ValueError("DA3 model is not ready")
    from .remote_da3 import remote_config
    config = remote_config()
    if not config["configured"] or not remote_model.startswith(config["url"] + "/api/runs/") or not remote_model.endswith("/model"):
        raise ValueError("Remote model URL does not match the configured DA3 PC")
    with urlopen(Request(remote_model, headers={"X-PitDivers-Token": os.environ["PITDIVERS_REMOTE_TOKEN"]}), timeout=120) as source, (output / "scene.glb").open("wb") as target:
        size = 0
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > 1024 * 1024 * 1024:
                (output / "scene.glb").unlink(missing_ok=True)
                raise ValueError("DA3 model exceeds 1 GB")
            target.write(chunk)
    record["remote_model_url"] = remote_model
    record["model_file"] = "scene.glb"
    record["model_error"] = None
    metadata.write_text(json.dumps(record, indent=2), encoding="utf-8")
    frames = json.loads((output / "frames.json").read_text(encoding="utf-8"))
    sensors = _sensor_evidence(capture, frames)
    room = json.loads((output / "source.json").read_text(encoding="utf-8"))
    _html(output / "report.html", output, capture, frames, sensors, room, record)
    return record


def _html(destination: Path, output: Path, capture: Path, frames: list[dict],
          sensors: list[dict], room: dict, record: dict) -> None:
    esc = lambda value: html.escape(str(value or ""), quote=True)
    count = len(frames)
    indices = sorted(set(round(i * (len(frames) - 1) / max(1, count - 1)) for i in range(count)))
    photos = []
    for index in indices:
        frame = frames[index]
        with Image.open(capture / frame["file"]) as source:
            source = source.convert("RGB")
            source.thumbnail((1000, 750))
            buffer = BytesIO()
            source.save(buffer, format="JPEG", quality=78, optimize=True)
        photos.append({"name": frame["file"], "at": frame["captured_at"] or "Time unavailable",
                       "url": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")})
    chart = []
    count = min(1200, len(sensors))
    indices = sorted(set(round(i * (len(sensors) - 1) / max(1, count - 1)) for i in range(count)))
    for index in indices:
        item = sensors[index]
        payload = item.get("sensors") or {}
        chart.append({"at": item.get("captured_at") or item.get("dashboard_received_at") or str(index),
                      "t": payload.get("temperature_c") if isinstance(payload.get("temperature_c"), (int, float)) and math.isfinite(payload["temperature_c"]) else None,
                      "h": payload.get("humidity_percent") if isinstance(payload.get("humidity_percent"), (int, float)) and math.isfinite(payload["humidity_percent"]) else None})
    js_data = json.dumps({"photos": photos, "chart": chart}, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    layers = "".join(f'<div class="map-layer{" active" if name == "map" else ""}" data-layer="{name}">{(output / f"{name}.svg").read_text(encoding="utf-8")}</div>' for name in ("map", "temperature", "humidity"))
    readings = []
    for index, point in enumerate(room["map"].get("environment", []), 1):
        if len(point) < 6 or not all(isinstance(point[j], (int, float)) and math.isfinite(point[j]) for j in (0, 1, 2, 3, 5)):
            continue
        readings.append(f"<tr><td>{index}</td><td>{point[0]:.2f}</td><td>{point[1]:.2f}</td><td>{point[2]:.1f}</td><td>{point[3]:.1f}</td><td>{point[5]:.0f}</td></tr>")
    video = '<video controls preload="metadata" src="video.mp4" style="width:100%;max-height:440px"></video>' if record["video_url"] else "Video not recorded for this capture"
    model_url = "scene.glb" if record["model_file"] else None
    model = (f'<model-viewer src="{esc(model_url)}" camera-controls auto-rotate style="display:block;width:100%;height:500px;background:#0d1d26;border-radius:8px" alt="Interactive DA3 reconstruction"></model-viewer><p><a href="{esc(model_url)}" download>Download GLB</a></p>' if model_url else f'DA3 model not yet available. {esc(record["model_error"] or "Send the capture to DA3 and regenerate this report once reconstruction finishes.")}')
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PitDivers inspection · {esc(record["asset"])}</title>
<style>
:root{{font:16px system-ui,sans-serif;color:#e7f4f4;background:#0a131a}}*{{box-sizing:border-box}}body{{margin:0 auto;max-width:1320px;padding:24px}}h1{{font-size:30px;margin:8px 0}}h2{{font-size:20px;margin:0 0 16px}}p{{line-height:1.5}}small,.muted{{color:#a5b8c3}}header,section{{background:#13232d;border:1px solid #2b414c;border-radius:14px;padding:22px;margin:0 0 18px}}header{{background:linear-gradient(130deg,#132c35,#15202d)}}.eyebrow{{color:#69dfc0;font-size:12px;letter-spacing:.13em;font-weight:700}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.metric{{background:#0d1d26;border:1px solid #2b414c;border-radius:10px;padding:14px}}.metric b{{display:block;margin-top:6px;font-size:16px}}button,.button,a.action{{font:inherit;background:#1c3540;color:#dff9f5;border:1px solid #42616b;border-radius:9px;padding:9px 14px;cursor:pointer;text-decoration:none}}button.active,.button:hover{{background:#61dfbb;color:#0c2824}}.tabs{{display:flex;gap:8px;margin:10px 0 18px;flex-wrap:wrap}}.map-layer{{display:none;background:#f7f9fc;border-radius:9px;overflow:hidden}}.map-layer.active{{display:block}}.map-layer svg{{display:block;width:100%;height:auto;max-height:720px}}.gallery{{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:16px}}#photo{{display:block;width:100%;max-height:570px;object-fit:contain;background:#071018;border-radius:8px}}.photo-tools{{display:flex;gap:8px;margin:12px 0;align-items:center}}input[type=range]{{width:100%}}canvas{{width:100%;height:300px;background:#0d1d26;border:1px solid #2b414c;border-radius:8px}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:8px;border-bottom:1px solid #35505b;text-align:right}}.scroll{{max-height:380px;overflow:auto}}a{{color:#73d9ff}}.warning{{border-left:4px solid #ef9b3a;padding:10px 14px;background:#29251d}}textarea{{width:100%;min-height:100px;background:#0d1d26;border:1px solid #42616b;border-radius:8px;color:inherit;padding:12px;font:inherit}}.links{{display:flex;flex-wrap:wrap;gap:16px}}@media(max-width:850px){{.grid{{grid-template-columns:1fr 1fr}}.gallery{{grid-template-columns:1fr}}}}@media print{{:root{{color:#15283b;background:white}}header,section,.metric{{background:white;color:#15283b;border-color:#bbb}}button,.tabs,.photo-tools{{display:none}}.map-layer{{display:block;break-inside:avoid}}canvas{{border:1px solid #ccc}}}}
</style><script type="module" src="model-viewer.min.js"></script></head><body>
<header><div class="eyebrow">PITDIVERS / MINING INSPECTION</div><h1>{esc(record["asset"])}</h1><p>{esc(record["notes"] or "No operator notes supplied.")}</p><small>Report {esc(record["id"])} · Created {esc(record["created_at"])} · Operator review required</small></header>
<section><h2>Inspection evidence</h2><div class="grid"><div class="metric">LiDAR room<b>{esc(record["room_id"])}</b></div><div class="metric">Camera capture<b>{esc(record["capture"])}</b></div><div class="metric">Photos<b>{record["frame_count"]}</b></div><div class="metric">Sensor samples<b>{record["sensor_samples"]}</b></div></div><p class="warning">{esc(record["source_association"])}</p><p>Temperature: {esc(record["temperature"])}<br>Humidity: {esc(record["humidity"])}</p><p>Positioned map readings — temperature: {esc(record["mapped_temperature"])}; humidity: {esc(record["mapped_humidity"])}.</p></section>
<section><h2>LiDAR and environmental layers</h2><div class="tabs" id="mapTabs"><button class="active" data-layer="map">LiDAR map</button><button data-layer="temperature">Temperature</button><button data-layer="humidity">Humidity</button></div>{layers}<p class="muted">Dark cells are occupied, light cells observed free space. Colored points are measurements at estimated rover positions; blank areas are unmeasured.</p></section>
<section><h2>Camera evidence</h2><div class="gallery"><div><img id="photo" alt="Selected camera frame"><div class="photo-tools"><button id="previous">Previous</button><input id="photoRange" type="range" min="0" max="{max(0,len(photos)-1)}" value="0" aria-label="Frame timeline"><button id="next">Next</button></div><small id="photoCaption"></small></div><div><p>All {len(photos)} recorded keyframes. Use the timeline to inspect the scene.</p></div></div></section>
<section><h2>Recorded video</h2>{video}</section>
<section><h2>DA3 3D model</h2>{model}</section>
<section><h2>Ambient sensor history</h2><div class="tabs" id="chartTabs"><button class="active" data-kind="t">Temperature</button><button data-kind="h">Humidity</button></div><canvas id="sensorChart" width="1100" height="300" role="img" aria-label="Sensor time series"></canvas><p class="muted">These readings describe air at the rover, not a machine bearing or wall surface. The complete sensor sample file is linked below.</p></section>
<section><h2>AI observations</h2><p class="muted">Model: {esc(record["ai"].get("model") or "Not used")} · Status: {esc(record["ai"]["status"])}</p><p>{esc(record["ai"]["text"]).replace(chr(10), '<br>')}</p><p class="warning">AI observations are unverified. Confirm findings against original frames and site procedures before acting.</p></section>
<section><h2>All positioned environmental readings</h2><div class="scroll"><table><thead><tr><th>#</th><th>X m</th><th>Y m</th><th>Temp °C</th><th>RH %</th><th>Age ms</th></tr></thead><tbody>{''.join(readings) or '<tr><td colspan="6">No positioned readings</td></tr>'}</tbody></table></div></section>
<section><h2>Reviewer decision</h2><p>Record the human assessment, follow-up and sign-off here. Use Download reviewed HTML to keep a copy with these notes.</p><textarea id="review" aria-label="Reviewer decision" placeholder="Reviewer, date, finding, action, and uncertainty"></textarea><div class="photo-tools"><button id="downloadReview">Download reviewed HTML</button><button onclick="window.print()">Print / save as PDF</button></div></section>
<section><h2>Source files</h2><div class="links"><a href="source.json">LiDAR JSON</a><a href="frames.json">Frame metadata</a><a href="map.svg">Map SVG</a><a href="temperature.svg">Temperature SVG</a><a href="humidity.svg">Humidity SVG</a>{'<a href="sensors.jsonl">All sensor samples</a>' if record["sensor_file"] else ''}<a href="report.json">Report data</a></div></section>
<script id="evidenceData" type="application/json">{js_data}</script><script>
const evidence=JSON.parse(document.getElementById('evidenceData').textContent);let photoIndex=0,kind='t';
const photo=document.getElementById('photo'),range=document.getElementById('photoRange');
function showPhoto(n){{if(!evidence.photos.length)return;photoIndex=Math.max(0,Math.min(evidence.photos.length-1,n));const item=evidence.photos[photoIndex];photo.src=item.url;range.value=photoIndex;document.getElementById('photoCaption').textContent=`${{photoIndex+1}} / ${{evidence.photos.length}} · ${{item.name}} · ${{item.at}}`;}}
range.addEventListener('input',()=>showPhoto(Number(range.value)));document.getElementById('previous').onclick=()=>showPhoto(photoIndex-1);document.getElementById('next').onclick=()=>showPhoto(photoIndex+1);showPhoto(0);
document.querySelectorAll('#mapTabs button').forEach(button=>button.onclick=()=>{{document.querySelectorAll('#mapTabs button').forEach(x=>x.classList.toggle('active',x===button));document.querySelectorAll('.map-layer').forEach(x=>x.classList.toggle('active',x.dataset.layer===button.dataset.layer));}});
const canvas=document.getElementById('sensorChart'),ctx=canvas.getContext('2d');function drawChart(){{const points=evidence.chart.map((p,i)=>({{x:i,y:p[kind]}})).filter(p=>Number.isFinite(p.y));ctx.clearRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#a5b8c3';ctx.font='14px system-ui';if(!points.length){{ctx.fillText('No valid sensor history',24,40);return;}}const ys=points.map(p=>p.y),min=Math.min(...ys),max=Math.max(...ys),span=Math.max(1,max-min),left=55,top=20,width=canvas.width-80,height=canvas.height-55;ctx.strokeStyle='#36515a';for(let i=0;i<4;i++){{let y=top+height*i/3;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(left+width,y);ctx.stroke();ctx.fillText((max-span*i/3).toFixed(1),6,y+4);}}ctx.beginPath();ctx.strokeStyle=kind==='t'?'#ff7433':'#29d3c2';ctx.lineWidth=3;points.forEach((p,i)=>{{let x=left+width*p.x/Math.max(1,evidence.chart.length-1),y=top+height*(max-p.y)/span;i?ctx.lineTo(x,y):ctx.moveTo(x,y);}});ctx.stroke();ctx.fillStyle='#e7f4f4';ctx.fillText(kind==='t'?'Temperature (°C)':'Humidity (% RH)',left+8,top+16);}}
document.querySelectorAll('#chartTabs button').forEach(button=>button.onclick=()=>{{kind=button.dataset.kind;document.querySelectorAll('#chartTabs button').forEach(x=>x.classList.toggle('active',x===button));drawChart();}});drawChart();
const review=document.getElementById('review');try{{review.value=localStorage.getItem('pitdivers-review-{record["id"]}')||review.textContent;}}catch{{}}review.addEventListener('input',()=>{{try{{localStorage.setItem('pitdivers-review-{record["id"]}',review.value)}}catch{{}}}});document.getElementById('downloadReview').onclick=()=>{{review.textContent=review.value;const blob=new Blob(['<!doctype html>'+document.documentElement.outerHTML],{{type:'text/html'}}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='pitdivers-{record["id"]}-reviewed.html';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}};
</script></body></html>'''
    destination.write_text(page, encoding="utf-8")


def _pdf(destination: Path, output: Path, capture: Path, frames: list[dict], room: dict, record: dict) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as PdfImage, Table, TableStyle, PageBreak
    from xml.sax.saxutils import escape

    styles = getSampleStyleSheet()
    story = [Paragraph("PitDivers | Mining inspection report", styles["Title"]), Spacer(1, 12)]
    for label, value in (("Asset / area", record["asset"]), ("Created (UTC)", record["created_at"]),
                         ("LiDAR room", record["room_id"]), ("Camera capture", record["capture"]),
                         ("Frames", str(record["frame_count"])), ("Temperature", record["temperature"]),
                         ("Sensor samples", str(record["sensor_samples"])),
                         ("Humidity at camera frames", record["humidity"]),
                         ("Temperature on LiDAR map", record["mapped_temperature"]),
                         ("Humidity on LiDAR map", record["mapped_humidity"])):
        story.append(Paragraph(f"<b>{escape(label)}:</b> {escape(str(value))}", styles["Normal"]))
        story.append(Spacer(1, 5))
    story += [Spacer(1, 14), Paragraph("Operator notes", styles["Heading2"]),
              Paragraph(escape(record["notes"] or "No notes supplied."), styles["BodyText"]),
              Spacer(1, 10), Paragraph("Source association", styles["Heading2"]),
              Paragraph(escape(record["source_association"]), styles["BodyText"]),
              Spacer(1, 12), Paragraph("AI observations — review required", styles["Heading2"]),
              Paragraph(escape(record["ai"]["text"]).replace("\n", "<br/>"), styles["BodyText"]),
              Spacer(1, 12), Paragraph("LiDAR floor plan", styles["Heading2"]),
              PdfImage(str(output / "map.png"), width=500, height=345),
              Paragraph("Dark: occupied; light: observed free; green: rover path. DA3 is visual evidence, not a metric extension of this LiDAR map.", styles["Italic"]),
              PageBreak(), Paragraph("Positioned environmental measurements", styles["Heading1"]),
              Paragraph("These are measured samples at estimated rover positions. Blank areas were not measured.", styles["BodyText"]),
              PdfImage(str(output / "temperature.png"), width=500, height=345),
              Spacer(1, 12), PdfImage(str(output / "humidity.png"), width=500, height=345),
              PageBreak(), Paragraph("Photographic evidence", styles["Heading1"])]
    selected = [frames[i] for i in sorted(set(round(i * (len(frames) - 1) / min(5, len(frames) - 1)) for i in range(min(6, len(frames))))) ] if len(frames) > 1 else frames
    for item in selected:
        image = capture / item["file"]
        with Image.open(image) as source:
            w, h = source.size
        scale = min(430 / w, 240 / h)
        story += [Paragraph(escape(f"{item['file']} · {item['captured_at'] or 'time unavailable'}"), styles["Heading3"]),
                  PdfImage(str(image), width=w * scale, height=h * scale), Spacer(1, 10)]
    story += [PageBreak(), Paragraph("Evidence inventory", styles["Heading1"]),
              Paragraph("The complete LiDAR JSON, three SVG map layers, all camera frame metadata, sensor samples, and this report's data are saved beside the PDF.", styles["BodyText"]),
              Paragraph(f"Capture: {escape(record['capture'])} | LiDAR room: {escape(record['room_id'])} | DA3 model: {escape(record['model'] or record['remote_model_url'] or 'not available')}", styles["BodyText"]),
              Paragraph(f"Video: {escape(record['video_url'] or 'not recorded')}", styles["BodyText"]),
              Paragraph("Temperature and humidity are ambient readings at the rover. AI observations are unverified and require an operator decision.", styles["Italic"])]
    samples = [p for p in room["map"].get("environment", []) if len(p) >= 6 and
               all(isinstance(p[j], (int, float)) and math.isfinite(p[j]) for j in (0, 1, 2, 3, 5))]
    if samples:
        story += [Spacer(1, 12), Paragraph("All positioned environmental readings", styles["Heading2"])]
        rows = [["#", "X m", "Y m", "Temp C", "RH %", "Age ms"]]
        for i, p in enumerate(samples, 1):
            rows.append([str(i), f"{p[0]:.2f}", f"{p[1]:.2f}", f"{p[2]:.1f}", f"{p[3]:.1f}", f"{p[5]:.0f}"])
        table = Table(rows, colWidths=[32, 70, 70, 70, 70, 70], repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dce6ef")),
                                   ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#ccd5df")),
                                   ("FONTSIZE", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story.append(table)
    doc = SimpleDocTemplate(str(destination), pagesize=A4, leftMargin=42, rightMargin=42, topMargin=42, bottomMargin=42)
    doc.build(story)
