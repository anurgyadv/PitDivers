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

## Dashboard frontend

The browser UI is a React + TypeScript app (Vite, Tailwind CSS, Framer Motion,
Lucide icons) in `webapp/frontend`. FastAPI serves its production build from
`webapp/frontend/dist`, which is committed so the Python launcher works without
Node installed.

Only rebuild the UI if you change the frontend source. It needs Node 20+:

```powershell
cd webapp/frontend
npm install
npm run build      # writes webapp/frontend/dist, then FastAPI serves it
```

For live UI development with hot reload, run the dashboard (`python -m webapp`)
and, in a second terminal, `npm run dev` in `webapp/frontend`. The dev server on
`http://127.0.0.1:5173` proxies `/api` and the MJPEG streams to the dashboard on
port 8765.

## Normal workflow

1. Open **Live**, enter the raw ESP32 URL such as
   `http://192.168.0.69:81/stream`, select a downloaded model, and connect.
   The dashboard derives `http://<camera-ip>:82/sensors` automatically and
   displays the DHT11 readings and graphs; no separate sensor URL is required.
   Graph history is kept in the browser for the current dashboard session.
2. Enter a capture name and press **Start recording**. The original stream
   frames are saved under `data/<capture-name>` at the selected keyframe rate.
3. Stop recording, open **Captures**, review the photos, then choose
   **Build 3D**.
4. The dashboard disconnects live mode before reconstruction to avoid two DA3
   processes competing for GPU memory. Progress and logs appear under
   **3D Models**.
5. Open the finished scene in the integrated viewer or download its GLB file.

Only one reconstruction runs at a time. The **Stop** button terminates its DA3
subprocess if a run is too large or stalls.

## Models

DA3 Small and Base are the practical live choices for the RTX 5070. Large 1.1
can be tried for offline reconstruction. Giant and Nested checkpoints are
listed for completeness but are likely to exceed 12 GB VRAM during multi-view
processing. Always check the licence displayed beside a model before use.

Downloaded models live in the standard Hugging Face cache, not in this
repository. An `HF_TOKEN` environment variable is optional but improves Hub
download rate limits.
