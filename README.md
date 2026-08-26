# PitDivers Rover Vision

PitDivers is an ESP32-S3 rover vision prototype combining a live camera,
Depth Anything 3 depth estimation and reconstruction, and DHT11 environmental
telemetry in one local dashboard.

## Features

- ESP32-S3 MJPEG camera streaming
- Live Depth Anything 3 depth processing on an NVIDIA GPU
- Keyframe recording and photo review
- Offline GLB 3D reconstruction and full-screen model viewing
- Live DHT11 temperature and humidity values with rolling graphs
- Combined Freenove camera + DHT11 firmware for one-device operation

## Start the dashboard

On Windows, double-click `Start PitDivers Dashboard.cmd`. See
`webapp/README.md` for the complete workflow and `vision/requirements.txt` for
the Python dependencies.

## ESP32-S3 firmware

Open `firmware/PitDivers_Camera_DHT11/PitDivers_Camera_DHT11.ino` in Arduino
IDE. Follow the wiring and upload instructions in the firmware folder's
`README.md`. Real Wi-Fi credentials belong in the ignored `secrets.h`; commit
only `secrets.example.h`.

## Repository layout

| Path | Purpose |
|---|---|
| `firmware/` | Combined FNK0082 camera and DHT11 Arduino firmware |
| `vision/` | Live DA3 depth, mapping, and object-detection scripts |
| `webapp/` | FastAPI dashboard and browser interface |
| `third_party/depth-anything-3/` | Vendored DA3 source with local CLI/gallery fixes |

Captured frames, reconstructed runs, model weights, virtual environments,
local credentials, and build outputs are excluded from Git.

## Third-party licensing

Depth Anything 3 retains its upstream licence and notices in
`third_party/depth-anything-3`. Freenove-derived firmware support files are
covered by CC BY-NC-SA 3.0; see
`firmware/PitDivers_Camera_DHT11/FREENOVE_LICENSE.txt`. Model checkpoints may
have separate licences—check the selected model before distribution or
commercial use.
