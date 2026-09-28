# Hallway map and out-and-back mission

**29 September:** This historical plan is superseded by [automatic saved-map
localization and navigation](AUTOMATIC_LOCALIZATION.md). The current launcher
searches for the rover across the saved map using AMCL; returning it to A is
no longer a startup requirement.

**28 September implementation update:** The motor bridge, conservative path planner, ROS localization guard, dashboard `Go B & return` control, and ESP 600 ms stop lease are implemented. See [the current runbook](../mapping/README.md#saved-hallway-out-and-back-test). The planning notes below predate this implementation. A floor run remains unverified because the mounted LiDAR currently reports an obstruction in the rover's inferred forward direction; the live dashboard disables the button until that view clears.

## Desired result

The rover starts at a marked floor position **A**, maps the hallway, then receives a selected map goal **B** and drives to B and back to A. Arrival means within a configured position and heading tolerance. A failed leg stops; it does not skip ahead to the next leg.

## What runs now

The Freenove records valid LiDAR revolutions on microSD and has teleoperation with a 600 ms wheel-command lease plus Wi-Fi-loss stop. `mapping/start_ros_mapping.sh` runs the scan collector, RF2O odometry and SLAM Toolbox, and the dashboard at `http://127.0.0.1:8766/` displays the estimated pose and occupancy map. The map can be exported as JSON. The Mission Map editor can validate and simulate a route.

The hallway has already been scanned. The saved run is `data/lidar-maps/c3c666243fd2.json`, with 735 poses, 10,385 occupancy cells, and 75 placed temperature/humidity samples. Its raw scans are in the adjacent `.jsonl` file and the SQLite scan store. The last mapped rover pose is about 7.7 m from the first, so the existing capture does not show a completed return to the start. The ROS processes are currently stopped, and the last dashboard connection check timed out. `Save map` preserves a visual JSON snapshot; use `mapping/rebuild_saved_posegraph.sh` to reconstruct the serialized SLAM pose graph from this capture for localization. The dashboard's route is **not** connected to a motor controller. No automatic out-and-back button exists yet.

## Existing hallway capture and optional new capture

Use the saved map for viewing and choosing a destination. The first pose in this run is `[0, 0, 0]` and the final pose is approximately `[-2.56, 7.26, -1.22]` in metres and radians. These are *estimated map poses*, not surveyed physical coordinates. The physical start must be marked and the LiDAR heading matched when placing the rover for the return test. There is no need to repeat the hallway scan just to see the map.

The room dashboard now has a **Hallway route** preview. Select saved room `c3c666243fd2`, click **Mark B on map**, and click within 0.5 m of the recorded rover path. The click snaps B to the nearest recorded pose; A is the first pose. The green line is the taught outward path and the dashed amber line is the same path in reverse. The selected B and route metrics are saved under `data/lidar-routes/` and reload with the room. This is a visual route only; no wheel command is sent. The updated dashboard is running at `http://127.0.0.1:8767/` because the earlier process still occupies port 8766.

B is currently marked near `(-2.00, 6.04)` on the saved visual map, giving an estimated 17.08 m round trip. The offline reconstruction of the SLAM graph shifted its corresponding scan to approximately `(-1.78, 6.12)` in the localization frame, a 0.237 m difference. Future navigation goals must use the graph-frame coordinate, not the visual-map coordinate; the route store derives it by scan ID.

`mapping/start_saved_localization.sh` now starts a live ROS localization session against this saved graph. It skips all earlier scans and waits for **new** scans from the rover; it never drives the wheels. The graph was verified loaded with SLAM Toolbox active and a 5 cm occupancy map published. At the last check the rover was offline and the session had zero live poses. Its snapshot is `data/ros-map/localization-live.json`. Before trying motion, place the rover on physical mark A at the marked heading, power it, start LiDAR, and verify this snapshot gains fresh placed poses near A. If the position jumps or the map does not match the hallway, stop and correct localization rather than beginning the route.

To reconstruct the ROS localization graph from the existing run in WSL, source `/opt/ros/lyrical/setup.bash` and `~/pitdivers_ros/install/setup.bash`, then run `bash mapping/rebuild_saved_posegraph.sh`. It replays scan IDs 349–1083 from a copy of the database and writes `data/lidar-maps/c3c666243fd2-posegraph.posegraph` and `.data`. This is an offline conversion; it does not move the rover.

Only if the map needs improvement, capture another pass:

1. Clear the hallway of people, pets and loose cables. Put floor tape at A, with an arrow for starting heading, and at B. Keep the LiDAR at one height, unobstructed.
2. Confirm the rover's `/api/lidar/status` responds over Wi-Fi and the dashboard shows **Rover connected**. Start the Windows mapping dashboard if needed; in a separate PowerShell terminal run `wsl bash /mnt/c/Users/Anurag/Documents/ChatGPT/PitDivers/mapping/start_ros_mapping.sh`.
3. On the dashboard click **New room** to avoid old microSD scans, then **Start LiDAR**. Wait for **TRACKING** and a changing map before driving.
4. Teleoperate slowly from A toward B. Pause at B to let scans settle, then return along the corridor to A. Seeing A again helps close the mapping loop. If tracking reports uncertainty, stop and recover it before continuing.
5. At A and B, read the current `x, y, heading` from the dashboard. The same numbers can be read in PowerShell with `(Invoke-RestMethod http://127.0.0.1:8766/api/state).map.pose`. Record the room ID too. The live dashboard currently has **no click-to-place goal marker**; these recorded coordinates are the goal definition until a marker control is added.
6. Click **Save map** and export JSON/PNG. Keep A and B from this *same* ROS session. Do not use a coordinate from a different room session. Photograph the physical tape marks and note measured A–B distance as a map sanity check.

This establishes the map and measurable goals. It does not make the rover drive autonomously.

## Software needed for automatic B → A

1. **Map reuse:** save SLAM Toolbox's serialized pose graph and load it in `mode: localization` for the later run. Place the rover at A with the marked heading and verify its estimated map pose against A before arming motion. If the ROS process remains continuously running between mapping and the test, this restart step can be deferred for the first same-session trial.
2. **Navigation inputs:** publish live `map → odom → base_link → lidar_link` transforms and a current `nav_msgs/Odometry` velocity estimate. RF2O already publishes the odom transform; verify its odometry topic and timing. Measure and configure the real LiDAR offset from the rover centre; the current static transform assumes zero offset. Configure the rover footprint, inflation, speed and acceleration limits for the actual chassis.
3. **Motor bridge:** translate Nav2 `cmd_vel` into bounded differential left/right wheel commands for the Freenove. The bridge must issue `stop` on cancel, lost localization, stale scan, Wi-Fi failure, HTTP failure and process exit. Keep the ESP's 600 ms lease; do not replace it with a long-running command. No OpenRouter output reaches this bridge.
4. **Planner and obstacles:** configure Nav2 global/local costmaps from the occupancy map and live `/scan`, plus a collision monitor. Mark hallway side walls as occupied and B as free space. Set `stop_on_failure=true`.
5. **Mission:** create two `map` poses, `[B, A]`, with an optional short inspection pause at B. Submit them through Nav2's waypoint follower or Simple Commander only after the above interfaces pass. Show current pose, planned path, leg, goal tolerance and stop reason in the UI.

## Progressive proving sequence

1. With wheels lifted, send a short forward `cmd_vel`, then cancel it; verify the wheels stop within the lease. Repeat with unplugged Wi-Fi and a killed controller process.
2. On floor, use a taped 0.5 m goal in open space at minimum speed, with a person holding an emergency stop. Compare actual stopping point to map pose.
3. Try A → B only. Stop on stale map pose, an unexpected obstacle, a blocked path or a time limit.
4. Only after a successful one-way run, execute B → A. Repeat from A after a ROS restart to prove actual map reuse.

## Demo cut line

For 29 September, show the **manual hallway teaching pass**, map with A and B, and supervised teleoperated travel between them. If autonomous software passes the lifted-wheel and short-distance tests, show the automatic leg as an extra. If it does not, show Nav2 planning in simulation and state clearly that physical execution remains under test.

This matters especially in a straight, visually repetitive hallway: scan-based odometry can become ambiguous. A measured A/B position check, wheel encoders or fixed visual markers would strengthen the repeatability claim.

## References

- [SLAM Toolbox serialization and localization](https://github.com/SteveMacenski/slam_toolbox)
- [Nav2 odometry requirements](https://docs.nav2.org/rolling/configuration_and_development/first_time_robot_setup_guide/odom/setup_odom/)
- [Nav2 waypoint follower](https://docs.nav2.org/rolling/configuration_and_development/configuration_guide/core_servers/waypoint_follower/)
- [Nav2 collision monitor](https://docs.nav2.org/rolling/configuration_and_development/configuration_guide/core_servers/collision_monitor/)
