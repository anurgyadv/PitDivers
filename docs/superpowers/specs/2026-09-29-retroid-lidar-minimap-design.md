# Retroid LiDAR Minimap Design

## Goal

Extend the existing Retroid Pocket rover-controller APK so it keeps its current
camera and physical-controller behaviour while displaying the new LiDAR room map
as a bottom-left minimap. The operator can expand the map, collapse it with a
close button, and start or stop the LiDAR. The app prefers the accumulated map
from the Windows mapping dashboard and falls back to the rover's latest raw
360-degree scan when the PC is unavailable.

## Existing behaviour that must remain

- The camera board remains the main view.
- The Retroid left stick controls throttle and steering.
- B remains the emergency-stop button.
- Motor commands remain ordered on the dedicated 75 ms single-thread worker.
- The app enters controller mode on resume, sends zero before leaving, and
  restores Human mode on pause.
- Rover motion control remains separate from camera and LiDAR network work.

## Network endpoints and saved configuration

The app stores editable URLs in Android `SharedPreferences`:

- Camera URL, default `http://192.168.0.119/`.
- Windows map dashboard URL, default `http://192.168.0.57:8767`.
- LiDAR rover URL, default `http://192.168.0.99`.
- Existing motion-controller address remains `192.168.0.118` with the existing
  API key and command protocol.

A settings dialog validates that each editable value is an HTTP or HTTPS URL,
normalises trailing slashes, saves valid values, and reloads the camera and map
connections without restarting the APK. Invalid values stay in the dialog with
a clear error message.

The Windows dashboard gains a `--host` argument. Its launch script uses
`0.0.0.0` so `/api/state` can be read from the Retroid on the trusted local
network. Existing default behaviour remains loopback-only when `--host` is not
provided. LiDAR start and stop are sent directly to the rover, so the Android
app does not need remote access to the dashboard's control endpoints.

## Android interface

The camera WebView fills the landscape screen as it does now. Native Android
overlays sit above it:

- The existing controller-status banner remains at the top.
- A compact LiDAR card occupies the bottom-left corner. It contains a native
  map canvas, source/status text, and a LiDAR On/Off button.
- Tapping the map canvas expands the card to the available screen. Expanded
  mode shows a close button in the top-right; pressing it returns the card to
  the bottom-left.
- A settings button opens the URL configuration dialog.
- No on-screen driving controls are added.

The map style follows the supplied reference: dark blue grid, filled explored
space, bright wall cells, live scan rays, travelled path, and a high-contrast
rover heading marker. The compact view automatically fits the current map.
Expanded mode preserves pinch-free, auto-fit behaviour so it is usable with
the Retroid controls and touchscreen without creating another navigation mode.

## Data flow and isolation

`MainActivity` retains the current dedicated control executor. LiDAR work uses
a second single-thread scheduled executor, so slow map or rover requests cannot
delay, overlap, or reorder motor commands.

Every 800 ms the LiDAR worker attempts to fetch `<dashboard>/api/state` with a
short timeout. Successful responses are converted into an immutable map model
and posted to the UI thread. The renderer uses the map's occupancy cells,
trajectory, current pose, tracking message, and live scan where available.

After three consecutive dashboard failures, the source changes to rover
fallback mode. The worker requests `<lidar-rover>/api/lidar/revolution` and
renders its 360 distance samples as a local polar scan centred on the rover.
Dashboard probing continues at a slower interval, and the accumulated map is
restored automatically after a successful response. Source and offline states
are shown in the LiDAR card without covering the camera.

The LiDAR toggle reads the latest known running state and posts to
`<lidar-rover>/api/lidar/start` or `/api/lidar/stop`. It is disabled while a
request is in flight, reports success or failure, and never shares the motor
control executor.

## Components

- `MainActivity`: lifecycle, existing controller transport, overlay state, and
  settings-dialog coordination.
- `LidarMapView`: native canvas rendering and compact/expanded tap handling.
- `LidarRepository`: dashboard polling, rover fallback, source selection, and
  LiDAR start/stop requests.
- `LidarModels`: immutable parsed map, pose, path, occupancy, scan, and status
  values. Malformed or missing optional values are ignored safely.
- Android layout and drawables: camera surface, compact card, expanded overlay,
  buttons, and status labels.
- `mapping/dashboard.py` and `mapping/start_demo.ps1`: configurable LAN binding
  for the existing `/api/state` feed.

## Failure and safety behaviour

- Camera failure does not stop controller input or LiDAR polling.
- PC dashboard failure changes only the map source; it does not change driving
  mode or stop the LiDAR.
- Rover LiDAR failure leaves the last valid drawing visible with an offline
  status and a retrying indicator.
- Pausing the app cancels LiDAR polling as well as the existing controller task.
- Destroying the activity shuts down both executors and the WebView.
- Map rendering never sends wheel commands.
- B emergency stop remains higher priority than ordinary joystick output.

## Testing and verification

- Unit tests for joystick mixing and deadzone behaviour retained from the
  current contract.
- Unit tests for dashboard JSON parsing, raw revolution parsing, malformed
  payload handling, source fallback, and URL normalisation.
- Renderer tests for empty, partial, compact, and accumulated-map models where
  practical; otherwise deterministic geometry helpers receive unit tests.
- Manual emulator verification with recorded fixture JSON for compact,
  expanded, close, settings, On/Off, PC loss, and recovery states.
- Gradle `assembleDebug` must pass, and the resulting APK path is reported.
- Final Retroid test verifies camera display, continuous joystick motion, B
  emergency stop, map expansion/collapse, LiDAR toggle, and PC-to-rover fallback.

## Out of scope

- On-screen steering controls.
- Editing routes or starting autonomous missions from the APK.
- Building an accumulated SLAM map on Android when the PC is absent. The rover
  fallback deliberately shows only the latest local 360-degree scan.
- MQTT migration or changes to the existing rover motion protocol.
