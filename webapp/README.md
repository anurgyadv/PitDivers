# PitDivers Rover Vision Console

The dashboard wraps the working ESP32 and Depth Anything 3 commands in a local
web application. It provides:

- live ESP32 MJPEG and DA3 depth views;
- live DHT11 temperature/humidity, HC-SR04 distance, and MPU6050 motion data
  from the combined rover firmware;
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
   displays DHT11, HC-SR04, and MPU6050 readings; no separate sensor URL is required.
   Graph history is kept in the browser for the current dashboard session.
2. Enter a capture name and press **Start recording**. The original stream
   frames are saved under `data/<capture-name>` at the selected keyframe rate.
   While recording, a **Captured keyframes** filmstrip appears directly below
   the streams and slides in each new frame as it is saved. It scrolls
   horizontally; drag or scroll back to inspect earlier frames (auto-scroll
   pauses while you do), and click any frame to open it full size.
3. Stop recording, open **Captures**, then **View photos**. In the photo grid
   you can **tick individual frames** (or **Select all** / **Clear**) and press
   **Build 3D from selected** to reconstruct only those frames; the ⛶ button on
   a frame opens it full size. Choosing **Build 3D** on the capture card instead
   uses every frame. Selecting a focused set of 25–40 sharp, well-spread frames
   is also the fix for a `CUDA error: out of memory` — feeding hundreds of
   frames into one run can exhaust GPU memory.
4. The dashboard disconnects live mode before reconstruction to avoid two DA3
   processes competing for GPU memory. Progress and logs appear under
   **3D Models**. Each job's terminal output is collapsed by default — use
   **Show terminal** / **Pop out** to inspect it, and **Dismiss** to clear a
   failed or cancelled job from the list.
5. Open the finished scene in the integrated viewer or download its GLB file.
   Use **Rename** on a model card to give a reconstruction a friendlier name.

The **Temperature** and **Humidity** readings render as large environment cards
with a live value, status pill, and rolling graph. Use either card's ⋮ menu to
pop its graph out in a larger window. The **Distance Ahead** card instead shows
a live four-zone safety arc (Stop, Caution, Clear, Safe). Click anywhere on that
card to open the full sonar safety dashboard with the 30-second distance graph,
approach rate, nearest and average distance, and echo-stability summary.
The sonar firmware and dashboard proxy run at 10 Hz (one sample every 100 ms),
the MPU6050 is sampled at 20 Hz, and the slower DHT11 remains on its independent
2-second reading interval. The **Rover Attitude** panel displays roll, pitch,
yaw, three-axis acceleration, three-axis angular rate, and IMU temperature.

Only one reconstruction runs at a time. The **Stop** button terminates its DA3
subprocess if a run is too large or stalls.

### Live depth readout

The depth panel shows a colour legend and a MIN / AVG / MAX / CONFIDENCE strip.

**These values are relative, not metres.** DA3-Base (and the other DA3 models in
the catalogue) output *up-to-scale* depth — the model reports the confidence flag
`is_metric = 0`, so there is no real-world scale. The readout therefore labels the
depth values `rel` and the legend "RELATIVE DEPTH" (NEAR → FAR), and the
confidence figure is the model's own uncalibrated per-pixel confidence expressed
as a relative 0–100% score. True metric depth would require a metric DA3 variant
(e.g. `da3metric-large`), which is not part of the current model catalogue; when
such a model is used the readout automatically switches to metres.

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
