# PitDivers Rover Vision Console

The dashboard wraps the working ESP32 and Depth Anything 3 commands in a local
web application. It provides:

- live ESP32 MJPEG and DA3 depth views;
- live DHT11 temperature/humidity values and rolling 10-minute graphs from the
  combined rover firmware;
- start/stop keyframe recording with named capture folders;
- capture and photo browsing;
- cancellable post-run GLB reconstruction jobs;
- an interactive, full-screen 3D model viewer and GLB downloads; and
- a model library for downloading supported DA3 checkpoints into the local
  Hugging Face cache.

## Start

Double-click `Start PitDivers Dashboard.cmd` in the project folder. It starts
the local service and opens `http://127.0.0.1:8765` automatically. Keep the
terminal window open while using the app. The launcher uses the project virtual
environment when available and falls back to the bundled local Python runtime
if the Windows Store interpreter behind the venv has moved.

Alternatively, from an activated project environment:

```powershell
python -m webapp
```

## Normal workflow

1. Open **Live**, enter the raw ESP32 URL such as
   `http://192.168.0.69:81/stream`, select a downloaded model, and connect.
   The dashboard derives `http://<camera-ip>:82/sensors` automatically and
   displays the DHT11 readings and graphs; no separate sensor URL is required.
   Graph history is kept in the browser for the current dashboard session.
2. Enter a capture name and press **Start recording**. The original stream
   frames are saved under `data/<capture-name>` at the selected keyframe rate.
   While recording, a **Captured keyframes** filmstrip appears directly below
   the streams and slides in each new frame as it is saved. It scrolls
   horizontally; drag or scroll back to inspect earlier frames (auto-scroll
   pauses while you do), and click any frame to open it full size.
3. Stop recording, open **Captures**, review the photos, then choose
   **Build 3D**.
4. The dashboard disconnects live mode before reconstruction to avoid two DA3
   processes competing for GPU memory. Progress and logs appear under
   **3D Models**.
5. Open the finished scene in the integrated viewer or download its GLB file.

The **Temperature** and **Humidity** metric tiles draw a live sparkline of the
DHT11 history right inside the tile. Hover a tile and click the ⤢ button to pop
the full graph out in a larger window. Both graphs plot a rolling 10-minute
window that fills from the left and scrolls rightwards as new readings arrive.

Only one reconstruction runs at a time. The **Stop** button terminates its DA3
subprocess if a run is too large or stalls.

### Reconstruction quality controls

The **Build 3D** dialog exposes the DA3 export quality levers so you can trade
cleanliness, detail, and GPU memory per run:

- **Processing resolution** — sharper depth per view at higher memory cost.
  Offline runs can go up to 1008 (live is capped lower for latency).
- **Confidence filter** — higher percentiles drop low-confidence floating and
  noise points. This is the single biggest clean-up lever; 55 is the default.
- **Point budget** — raise alongside resolution for a denser cloud (larger GLB).
- **Camera wireframes** — hidden by default so the exported scene isn't
  cluttered by camera-pose pyramids.

If a result still looks fuzzy, the dominant factor is input image quality, not
these settings — see [`docs/RECONSTRUCTION_QUALITY.md`](../docs/RECONSTRUCTION_QUALITY.md)
for the full roadmap (firmware still-capture, capture geometry, and meshing).

## Models

DA3 Small and Base are the practical live choices for the RTX 5070. Large 1.1
can be tried for offline reconstruction. Giant and Nested checkpoints are
listed for completeness but are likely to exceed 12 GB VRAM during multi-view
processing. Always check the licence displayed beside a model before use.

Downloaded models live in the standard Hugging Face cache, not in this
repository. An `HF_TOKEN` environment variable is optional but improves Hub
download rate limits.
