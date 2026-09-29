# PitDivers room mapping

## Saved hallway out-and-back test

The supervised route dashboard is at <http://127.0.0.1:8767/>. Its launcher binds the server to the private LAN so the Retroid APK can read `http://<windows-pc-ip>:8767/api/state`; allow Python through Windows Firewall only on private networks. Select saved room `c3c666243fd2`. The launcher now uses **AMCL global localization** to find the rover across the saved map without returning it to A. Wait for **Localized at current position**, then press **Go to B**. Scan agreement and pose uncertainty gate movement; repeated live rays update stale local obstacles. A data gap stops the rover, then it replans and continues after verified recovery. **STOP AUTO** cancels active and paused trips. See [the current runbook](../docs/AUTOMATIC_LOCALIZATION.md).

**29 September live result:** the one-way trip reached B, ROS reported approximately 12 cm remaining error and 97% scan agreement, the ESP confirmed `motion: stopped`, and the operator confirmed the physical destination. The return leg and bounded in-place turning have not yet been proven on the floor.

During saved-map localization, **Live room** shows the saved geometry with the current rover marker, verified current-session trail, and latest LiDAR scan. Local navigation obstacle updates do not overwrite the saved map. If the ESP reboots, start LiDAR and restart localization; AMCL searches the map again. To build new room geometry, stop saved localization and start the ROS mapping stack.

To start localization against the saved graph, keep the LiDAR spinning and run in PowerShell:

```powershell
wsl bash -lc '/mnt/c/Users/Anurag/Documents/ChatGPT/PitDivers/mapping/start_saved_localization.sh'
```

The dashboard enables travel only after localization passes scan agreement and uncertainty checks and the live forward sector has at least 0.45 m clearance. Keep the LiDAR mount fixed relative to the chassis; moving it requires recalibrating the forward axis. Intermittent multi-second scan gaps were observed during the successful run, so the controller's stopped recovery state remains necessary. No firmware flash was required for this navigation update.

## Open the visual dashboard

From the PitDivers folder in PowerShell:

```powershell
uv run --with numpy --with scipy --no-project python mapping/dashboard.py --host 0.0.0.0 --rover http://192.168.0.99
```

Open **http://127.0.0.1:8766/** on this PC. Keep the terminal running. The page shows a room occupancy map, estimated rover path, current LiDAR scan, temperature and humidity layers, tracking quality, and microSD recording state. Use **Start LiDAR** if the sensor is stopped. After a long pause or rover restart, use **New room** to establish a new origin; previous room snapshots stay saved.

`--host 0.0.0.0` exposes the dashboard on the trusted LAN for the Retroid. The
APK reads only `/api/state`; the dashboard's POST routes keep their existing
same-origin check. Without `--host`, the default remains loopback-only.

For the current chassis mounting, the dashboard D-pad corrects the rover's rotated response in software: **up sends the ESP `left` command, down sends `right`, left sends `backward`, and right sends `forward`**. This correction applies only to the room dashboard; the ESP's own web page remains unchanged until a later firmware flash. The command loop preserves a newly pressed direction while an earlier request is still finishing. Releasing a button requests `stop` immediately, and the ESP's 600 ms command lease remains the final stop safeguard. While driving, this dashboard pauses its own microSD backlog polling for one second after each command; the durable scan records are collected afterward.

Open **Rover controls & orientation** for the motor speed slider and meter. It reads the current ESP speed when opened and applies values from 80 to 255 PWM through the rover's existing `/speed` endpoint. It does not require a firmware flash. If the rover is offline, the dashboard shows that the chosen speed was not applied.

If an older dashboard remains open on port 8766 while an updated one runs on 8767, both poll the same single-client ESP web server. Close the older dashboard terminal before testing control latency. If the ESP itself times out at its `/api/status` endpoint, dashboard timing changes cannot restore the Wi-Fi connection; check its power, Wi-Fi address, and Serial Monitor before driving.

The dashboard runs directly on Windows using incremental LiDAR scan matching. It can build a room estimate as the rover moves slowly. It does **not** perform loop closure and cannot guarantee a drift-free survey; uncertain scans remain unplaced. The first accepted scan defines the room origin. The temperature layer colours observations at the rover position, with fresh DHT measurements deduplicated; it does not infer temperatures on walls or across unmeasured space. IMU data remains in the raw log but is not fused into this mapper's pose estimate.

**Save map** preserves the map locally, and the Saved map selector opens earlier snapshots. **Export image** downloads the selected view as PNG. **Map JSON** includes occupancy cells, trajectory and environmental observations. **Sensor data** exports full scan payloads with their estimated poses, or `map_pose: null` for rejected scans. Raw observations remain in `mapping/room_scans.sqlite3`; room snapshots auto-save every 10 seconds under `data/lidar-maps/`. Pausing mapping keeps collection running. LiDAR spin and wheel movement only change when you use their explicit controls.

## Optional ROS installation in WSL

To install ROS 2 Lyrical, SLAM Toolbox, RViz and RF2O on the existing Ubuntu 26.04 WSL installation, run this in PowerShell and enter the Ubuntu password in the terminal:

```powershell
wsl bash /mnt/c/Users/Anurag/Documents/ChatGPT/PitDivers/mapping/setup_ros.sh
```

This uses the official ROS apt-source package and RF2O repository. Start the installed ROS pipeline in a second PowerShell terminal:

```powershell
wsl bash /mnt/c/Users/Anurag/Documents/ChatGPT/PitDivers/mapping/start_ros_mapping.sh
```

The dashboard automatically displays the ROS snapshot when `data/ros-map/live.json` exists. Its footer identifies **RF2O + SLAM Toolbox**, with loop closure enabled. Keep both terminals running. Initial startup replays the Linux scan database. **New room** saves the current snapshot, restarts the ROS nodes and processes newly collected scans; allow about 10 seconds for the reset. Start LiDAR, wait for tracking, then drive slowly. A rover reboot or scan gap over three seconds stops pose processing until New room is used. Sensor logging continues regardless. Pause mapping is disabled in ROS mode.

ROS uses its own Linux database at `~/pitdivers_ros/room_scans.sqlite3`; it never writes the Windows WAL database. During ROS sessions the Windows dashboard polls the live LiDAR and publishes `data/ros-map/latest-rover.json` for the WSL bridge. This keeps a single rover scan reader while the microSD archive catches up later. Atomic JSON snapshots cross the WSL/Windows boundary. A stopped ROS process leaves the last map visible and marked offline. Environmental coordinates and trajectory points are estimates when captured; they are not retrospectively deformed with SLAM loop-closure corrections. IMU data is retained, not fused. JSON exports save the occupancy map and observations, not a resumable SLAM pose graph. Hardware motion and loop-closure accuracy still need a driving trial.

The Freenove ESP32-S3 records every **complete, checksum-valid 360° LiDAR revolution** to `/pitdivers_scans.jsonl` on its microSD card. Each JSON record includes `boot_id`, scan sequence, rover uptime timestamps, 360 distances in millimetres, RPM, temperature, humidity, reading age, and MPU6050 acceleration/gyro readings. The record is self-contained, so Wi-Fi loss does not erase the environmental observations. The PC's SQLite collector resumes from its saved SD byte offset when Wi-Fi returns. Map coordinates are computed on the PC from the scans; the ESP cannot know them while disconnected.

## Firmware and pin allocation

Flash [freenove_room_mapping.ino](../firmware/SKETCHES/freenove_room_mapping/freenove_room_mapping.ino) with Arduino IDE board **ESP32S3 Dev Module**, **8 MB flash**, the **Default 8MB** partition scheme, and OPI PSRAM. COM3's chip reports 8 MB flash; a 16 MB image boot loops. The sketch folder contains a copy of your existing ignored `secrets.h`. Keep the microSD inserted and formatted FAT32.

| Function | Freenove GPIO |
| --- | --- |
| L298N IN1, IN2, IN3, IN4 | 1, 2, 41, 42 |
| LDS02RR TX → ESP RX | 14 |
| LiDAR motor MOSFET gate | 47 |
| DHT11 data | 21 |
| MPU6050 SDA, SCL | 3, 48 |
| microSD CMD, CLK, D0 | 38, 39, 40 |

The LiDAR and its spin motor need a regulated **5 V** supply; all grounds must be common. Never feed the ESP GPIO with a 5 V signal. Check the ESP Serial Monitor at 115200 baud for `microSD scan log ready` and the Wi-Fi URL. The sensor must complete at least one turn before the new endpoint has data.

For the stated rover IP, open:

- `http://192.168.0.99/api/records/status` — card state, log size, sequence, write errors.
- `http://192.168.0.99/api/lidar/revolution` — latest complete payload with environment and IMU.
- `http://192.168.0.99/api/records?offset=0` — first four stored NDJSON records. The `X-Next-Offset` response header is the next byte offset.

## Collect scans, including Wi-Fi outage backlog

Run from the project root (Windows or WSL):

```sh
python mapping/collect.py --rover http://192.168.0.99 --db mapping/room_scans.sqlite3
```

If the rover is offline, the collector waits and retries. The SQLite transaction saves scans and the next SD offset together. Keep the microSD card in the rover until catch-up finishes. If `/api/records/status` says `storage_ok: false`, fix the SD card before relying on outage recovery. The app may also run on Windows with the project's Python runtime. **Run collector and ROS bridge on the same OS** so both see consistent SQLite file locks.

## Build a room map with ROS 2

This part runs in Ubuntu/WSL with a ROS 2 installation. Follow the [official ROS installation guide](https://docs.ros.org/en/lyrical/Installation.html) for the Ubuntu/ROS version installed; this workspace's WSL Ubuntu 26.04 corresponds to ROS 2 Lyrical. Install `slam_toolbox`, `rviz2`, `rclpy`, `sensor_msgs`, `tf2_ros`, and build the [RF2O ROS 2 branch](https://github.com/MAPIRlab/rf2o_laser_odometry/tree/ros2) in a colcon workspace.

Start four terminals, all using the **same ROS environment** and with this repository as the working directory:

```sh
python3 mapping/collect.py --rover http://192.168.0.99
```

```sh
ros2 launch rf2o_laser_odometry rf2o_laser_odometry.launch.py
```

```sh
ros2 launch slam_toolbox online_async_launch.py
```

```sh
python3 mapping/ros_bridge.py --db mapping/room_scans.sqlite3 --forward-index 0
```

Then run `rviz2`, add `/map` as a Map display and `/scan` as a LaserScan display, and set fixed frame `map`. Drive the rover slowly and revisit areas to help scan matching. RF2O estimates wheel-free odometry from the scans; SLAM Toolbox combines that with scan matching into an occupancy map. [SLAM Toolbox documents the `/scan` and odometry transform inputs](https://github.com/SteveMacenski/slam_toolbox), and [RF2O's ROS 2 launch file](https://github.com/MAPIRlab/rf2o_laser_odometry/blob/ros2/launch/rf2o_laser_odometry.launch.py) uses `/scan`, `odom`, and `base_link`.

`--forward-index` must match the raw LiDAR angle pointing toward the rover's front; the default is an assumption. Add `--counterclockwise` if raw angles increase that way. Also measure the LiDAR position relative to the rover centre and update `publish_mount_tf()` in `ros_bridge.py` before using map dimensions as measurements. The mapping process fills `map_x_m`, `map_y_m`, and `map_yaw_rad` in SQLite when a `map → base_link` transform is available. It leaves rows unplaced if a transform was unavailable; it never fabricates coordinates. The map starts at an arbitrary local origin, not GPS coordinates.

Render the environment layer once some scans have map poses:

```sh
python3 mapping/render_environment.py --field temperature --out mapping/temperature.svg
python3 mapping/render_environment.py --field humidity --out mapping/humidity.svg
```

The SVGs plot the rover's route and colour readings by value. Saved records still contain raw temperatures, humidity, and their age even when the mapping software has not yet assigned coordinates.
