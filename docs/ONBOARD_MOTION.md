# ESP onboard motion firmware

## What runs where

The Freenove owns a nominal 100 Hz FreeRTOS control task: LiDAR UART parsing,
IMU reads, gyro integration, full-power bounded turns, heading-hold steering,
motor PWM, obstacle stopping and command expiry. Its task does no HTTP, SD I/O,
JSON allocation or NVS writes. The web/storage task reads coherent snapshots
and a separate storage task consumes a 12-scan queue. Queue overflow is reported as dropped_log_scans.
Live scan HTTP always uses the newest sensor snapshot, independently of SD backlog.
SD writes and DHT sampling run on core 0, outside the HTTP loop. Log downloads
use a storage mutex and return busy instead of waiting for an SD write; log-size
telemetry is cached. These changes reduce command contention but do not guarantee
Wi-Fi latency.

The PC retains ROS scan matching, saved-map localization, A* and multi-stop
ordering. It sends small heading corrections while translating (normally every
200 ms). The ESP steers between those updates. A turn is sent once with an ID;
300 ms heartbeats do not restart it. The ESP stops at the measured angle. The
PC waits for a post-turn map position before translating again.

This is a complete firmware replacement for the hybrid architecture, **not
standalone SLAM or autonomous navigation through a Wi-Fi outage**. There are no
wheel encoders; the gyro does not establish XY position. Scans still go to the
PC for localization. Onboard scan matching/global localization needs its own
implementation and hardware benchmark; no map is uploaded by this version.

## Build and flash

From the project root in PowerShell:

```powershell
.\firmware\build_onboard_motion.ps1
```

Build artifacts and source hashes are in `data/build-onboard-motion` (ignored
by Git; binaries include your local Wi-Fi configuration). With the Freenove
connected by USB, close its Serial Monitor and substitute its actual port:

```powershell
.\firmware\build_onboard_motion.ps1 -Upload -Port COM3
```

The script uses the existing Arduino ESP32 package and DHTesp library. Board:
ESP32S3 Dev Module, 8 MB flash, OPI PSRAM. It never uploads without -Upload.
Firmware starts with motors stopped, LiDAR stopped, and gyro motion uncalibrated.
It does not resume a previous mission after reset.

Restart the existing ROS demo supervisor after deployment to load the updated
Python navigation code. If running in a terminal, Ctrl+C there, then:

```powershell
wsl -e python3 /mnt/c/Users/Anurag/Documents/ChatGPT/PitDivers/mapping/demo_stack.py
```

Reload the demo dashboard. Start scanning/LiDAR, then **Calibrate turns** on the
actual surface. Remain still for the bias measurement and allow two bounded
turns. A successful calibration is required each boot. Saved rates persist in
NVS, but old gyro bias is not silently reused for navigation. Finish/use the
map and plan a short supervised route. Status reports motion_backend=esp_gyro.
Older firmware remains supported through the original ROS motor-control path.

## Limits and stop behavior

- Turning: full duty 255, bias-corrected gyro angle, 3–6 degree coast allowance,
  1.5 s heartbeat, 1.5 s without measured progress, max 15 s duration. Wrong-way
  rotation beyond 5 degrees faults. Duplicate IDs cannot restart a completed turn.
- Translation: duty up to 200 (demo 180), gyro heading correction, 600 ms command
  lease. New corrections must originate from fresh localized PC measurements.
- Autonomous motion: fresh complete LiDAR scan <=350 ms, >=180 valid returns; >=45 cm
  in the direction of travel, or all around when spinning. Invalid sectors block.
- Gyro motion: gap <=100 ms, finite unsaturated samples, level IMU Z axis.
- Manual driving: no LiDAR clearance/freshness or gyro/calibration requirement.
  The operator holds a direction; command expiry after 600 ms, Wi-Fi loss and
  STOP still halt the motors. A new explicit manual command can recover a
  previous fault; reconnection alone cannot restart movement. Active autonomous
  motion or calibration must be stopped before taking manual control.
- Wi-Fi disconnect, autonomous sensor fault, operator STOP or control queue overflow stop
  locally. A local fault never resumes itself. The PC may recover only after its
  existing localization/clearance gates succeed and it explicitly stops/reissues.
- STOP is queued to the control task and processed on its next cycle; it is not
  a physical power-cut emergency stop. Hardware timing/braking must be tested.
- During accepted bounded turns, ROS pose lag alone does not split the turn into
  pulses. Local LiDAR/gyro/heartbeat checks remain in effect. Translation cannot
  start until a fresh map pose and scan from after the turn are available.

No measured end-to-end latency improvement is claimed until hardware testing.
The pure controller tests and ROS tests simulate input/fault sequences, not
motor torque, stopping distance, gyro mounting or actual scheduler timing.

## Wiring and coordinates

Unchanged: wheel channels GPIO1/2 and 41/42, LiDAR RX14/PWM47, DHT11 GPIO21,
MPU6050 SDA3/SCL48, microSD CMD38/CLK39/D040. Physical channel A is reversed.
The present ROS bridge uses clockwise raw scans with forward-index zero, and
chassis offset 2.936 radians: raw chassis-front index rounds to 192. The Python
client sends this explicit bearing with motion commands. If sensor mounting or
ROS scan orientation changes, update/validate this transformation too.

## Protocol

- GET `/api/capabilities`: `onboard_motion: 1`
- GET `/api/motion/status`: mode, id, ready, yaw/target, signed outputs,
  sensor/control ages, heap/PSRAM and SD queue drops
- POST `/api/motion?kind=turn&id=...&angle=90&front=192`
- POST `/api/motion/heartbeat?id=...`
- POST `/api/motion?kind=hold&id=...&angle=5&duty=180&front=192`
- GET `/stop`: cancel any motion and calibration
- Existing calibration, scan, environment, IMU, SD and wheel endpoints remain.

POST acknowledgement is queue acceptance. Turn status confirms actual execution
or fault. These endpoints run on the existing trusted local network and are not
intended for public Internet exposure.
