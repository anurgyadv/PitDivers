# PitDivers Rover Vision Console

The dashboard wraps the working ESP32 and Depth Anything 3 commands in a local
web application. It provides:

- live ESP32 MJPEG or repeated-JPEG snapshot feeds and DA3 depth views;
- hold-to-drive rover controls for a separate motion-controller ESP;
- dashboard-managed Xbox/XInput gamepad bridge;
- per-feed visibility switches for camera, depth, and semantic views;
- bounded object-seeking autonomy using YOLOE tracks with optional Ollama vision fallback;
- live YOLOE semantic masks, boxes, and session-stable object tracks;
- live DHT11 temperature/humidity, HC-SR04 distance, and MPU6050 motion data
  from the combined rover firmware;
- start/stop keyframe recording with named capture folders;
- capture and photo browsing;
- cancellable post-run GLB reconstruction jobs;
- an interactive, full-screen 3D model viewer and GLB downloads; and
- a model library for downloading supported DA3 checkpoints into the local
  Hugging Face cache; and
- a metric mission-map editor for importing manual teach traces, drawing safe
  boundaries and obstacles, placing inspection waypoints, and compiling a
  controller-neutral rover plan.

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

## One-dashboard inspection workflow

Run the dashboard on the laptop that shares Wi-Fi with the rover. The Windows
launcher also starts the local LiDAR collector and supervised room-mission
service. Open **Reports** to see the live LiDAR room interface in the dashboard.
Use its **Start new room scan**, manual drive, **Finish scan & use map**, route
preview, **Go & return**, and **STOP** controls only while supervising the rover.
The map service saves JSON in `data/lidar-maps/`; Reports lists those saved rooms.

On **Live**, choose **Camera only · depth disabled** if the laptop has no NVIDIA
GPU. Connect the rover camera and start recording. A capture saves a 12 FPS
`video.mp4`, selected JPEG keyframes, frame timestamps and sensor snapshots,
plus IMU samples. The **Captures** page opens the video and frames. If the MP4
encoder is unavailable, recording continues with keyframes and the manifest
records the video error.

The **Setup** page has collapsible camera, wheel, sensor and DA3 PC connections.
The camera defaults to `http://192.168.0.119/jpg`; the wheel/LiDAR/sensor ESP
currently responds at `http://192.168.0.99`. Its environment and IMU data
come from `/api/environment` and `/api/imu`. The separate entries allow the
addresses to change without changing the camera configuration. The DA3 PC
entry accepts a private Tailscale Serve URL and shared token for this dashboard
session; the same token must already be set on the PC.

Use **Expedition** for a single-page run. Start connects the camera and rover,
starts LiDAR, and records video, keyframes and sensor samples. Hold the manual
drive buttons to move, release to stop, and open the small LiDAR map for the
full map controls. Stop saves the room map and capture, creates the HTML report
with the chosen OpenRouter vision model, and transfers selected frames to the
DA3 PC. The report opens immediately; when DA3 finishes, its GLB is copied
into that report's folder and the same HTML page is updated. The OpenRouter
key entered on Expedition is sent once to the local server and is not saved.
Corrected manual drive uses the firmware's signed `/api/wheels` endpoint; an
older ESP firmware without it must be updated before these controls can drive.

On **Reports**, choose the camera capture and saved LiDAR room, enter the asset
and operator notes, and generate an interactive HTML report. It includes all
recorded photos, video, a DA3 GLB viewer when available, AI observations, and
sensor history. Keep the complete `data/reports/<report-id>/` folder together
when moving the report: photos and SVG maps are embedded in the HTML; video,
GLB, viewer script, and source files sit beside it. It also saves `source.json`,
`frames.json`, and the map, temperature, and humidity SVG layers under
`data/reports/<report-id>/`. Mapped environmental samples and camera sensor
readings remain distinguished: air readings at the rover do not measure a
machine surface. A report can be generated without AI.

For optional OpenRouter observations, set `OPENROUTER_API_KEY` in the laptop's
environment before launching and enable the checkbox on Reports. The dashboard
sends at most six selected JPEG frames on demand, keeps the key on the server,
and labels the returned text as requiring operator review. The selected model
must accept image inputs. The report still generates if the API fails.

### Remote DA3 PC over Tailscale

The laptop controls the rover locally. The PC only receives saved frames for
offline DA3; it does not send drive commands. Both computers must be signed in
to the same tailnet. On the PC, start the vision dashboard with `python -m
webapp` and expose its local port privately with `tailscale serve 8765`. Set
the same long random `PITDIVERS_REMOTE_TOKEN` on both machines before starting
their dashboards. On the laptop also set `PITDIVERS_DA3_REMOTE_URL` to the PC's
Tailscale Serve HTTPS URL, without a trailing slash. Example PowerShell session:

```powershell
$env:PITDIVERS_REMOTE_TOKEN = '<your private random token>'
$env:PITDIVERS_DA3_REMOTE_URL = 'https://your-pc.your-tailnet.ts.net'
$env:OPENROUTER_API_KEY = '<your OpenRouter API key>'
.\run_dashboard.ps1
```

On the PC, set only the remote token and run `python -m webapp`; start
`tailscale serve 8765` in a separate terminal. On Reports, click **Send capture
to DA3 PC**, then **Check DA3**. The laptop transfers up to 120 evenly spaced
frames (maximum 512 MB), the PC queues its existing DA3 reconstruction, and
the status eventually provides a link to the PC's 3D model. An Expedition
report is created when recording stops and updated with the GLB after DA3
finishes. The report stays on the laptop. The PC needs its DA3 model and CUDA
GPU available.

## Normal workflow

### Controller and autonomous modes

The **Drive** page can start and stop `firmware/SKETCHES/rover_gamepad_bridge.ps1`
without opening a separate terminal. Enter the motion ESP URL and the same API
key compiled into its firmware, connect the controller, then select **Start
controller**. The dashboard launches one hidden PowerShell process and restores
Human mode when it stops.

For a bounded autonomous test, first connect the camera with **Live semantics**
enabled and connect the motion ESP. Enter a target under **Find and approach**.
The deterministic controller uses YOLOE boxes to scan, centre, and approach with
short motor leases. It stops after 60 unsuccessful steps, when the object fills
55% of the image height, or when valid sonar reports 30 cm or less.

Enable the Llama switch to use an Ollama vision model when YOLOE has no matching
class. The default model is `llama3.2-vision:11b`; install it separately with:

```powershell
ollama pull llama3.2-vision:11b
```

The model only proposes an object box. Deterministic code applies safety checks
and chooses the actual bounded movement command. Use **Emergency stop** at any
time to stop manual, controller, and autonomous motion.

The visibility switches on **Live** hide the camera, depth, or semantic cards
without disconnecting the processing pipeline, and the selection is remembered
in the browser.

1. Open **Live**, enter the raw ESP32 URL such as
   `http://192.168.0.69:81/stream`. The temporary camera sketch instead uses
   `http://<camera-ip>/jpg`. Select a downloaded model and connect.
   Select **Camera only · depth disabled** under **Live processing** when you
   want camera, sensor, and VIO recording without loading a DA3 model or using
   GPU inference. **Camera mode** independently selects **Quality · 640×480**
   for reconstruction or **VIO fast · 320×240** for a substantially faster
   feature-tracking stream.
The dashboard derives `http://<camera-ip>:82/sensors` automatically and
   displays DHT11, HC-SR04, and MPU6050 readings; no separate sensor URL is required.
   Graph history is kept in the browser for the current dashboard session.
   Open the dedicated **Drive** page for a single driver view that can switch
   object detection on or off and display either the original or enhanced feed.
   Its low-light controls provide **Off**, **Fast** temporal enhancement, and
   **AI** SCUNet neural denoising, plus a strength slider. Enhanced frames are
   also used by depth and semantic inference.
   In **Rover controls**, enter the separate motion ESP address (for example
   `http://192.168.0.70`) and connect. Hold the direction pad or W/A/S/D to
   drive; release to stop. The dashboard refreshes the motion lease while a
   direction is held, and the firmware stops automatically if requests cease.
2. Enter a capture name and press **Start recording**. The original stream
   frames are saved under `data/<capture-name>` at the selected keyframe rate.
   The same folder receives a continuous `imu.csv` containing sequenced 100 Hz
   MPU6050 readings in raw and SI units. Each frame's JSON sidecar carries the
   matching ESP32 camera timestamp, boot ID, and frame sequence for later VIO.
   A red elapsed-time marker beside the recording button shows the current
   session duration and remains accurate if the page refreshes.
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

### Live semantic overlay

On **Live**, leave **Live semantics** enabled to show a third stream with YOLOE
object masks, boxes, confidence, and a stable track ID such as `door_001`.
Semantic inference defaults to 1 FPS so it can share the GPU with DA3 depth;
raise it only when the GPU has headroom. If depth is enabled, each detection
also receives a relative depth sample (`z … rel`). These IDs are view-local to
the current camera session. They are timestamped with the camera frame, but
they are not world coordinates until VIO supplies camera pose.

The **Temperature** and **Humidity** readings render as large environment cards
with a live value, status pill, and rolling graph. Use either card's ⋮ menu to
pop its graph out in a larger window. The **Distance Ahead** card instead shows
a live four-zone safety arc (Stop, Caution, Clear, Safe). Click anywhere on that
card to open the full sonar safety dashboard with the 30-second distance graph,
approach rate, nearest and average distance, and echo-stability summary.
The sonar firmware and dashboard proxy run at 10 Hz (one sample every 100 ms),
the MPU6050 is sampled at 100 Hz, and the slower DHT11 remains on its independent
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
