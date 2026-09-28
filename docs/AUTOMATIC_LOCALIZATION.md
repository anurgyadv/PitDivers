# Automatic saved-map navigation

The saved-map launcher now uses ROS 2 AMCL with a uniform distribution across
all known free cells and headings. It does not seed the rover at A. RF2O supplies
incremental LiDAR odometry; AMCL supplies the map correction. SLAM Toolbox is
still used to build maps, but is not running alongside AMCL during navigation.

Run the dashboard, then in WSL:

```bash
bash /mnt/c/Users/Anurag/Documents/ChatGPT/PitDivers/mapping/start_saved_localization.sh c3c666243fd2
```

Leave the rover stationary while it locates itself. The dashboard shows scan
agreement and readiness. Choose the saved destination and press **Go to B**.
Process startup, map selection, and localization never start the wheels.

Readiness requires at least 50 usable returns, 60% of endpoints within 15 cm
of mapped occupied cells, median endpoint error at most 12 cm, estimated
position standard deviation at most 20 cm and heading deviation at most 15°.
The checks must hold across 15 fresh scans and at least three seconds.
These are confidence checks, not a guarantee of correct localization in a
repetitive or substantially changed environment.

The navigation costmap preserves the saved map and overlays local readings.
Three distinct scans must ray-clear an old occupied cell before that cell is
cleared. New returns immediately mark obstacles. Unknown space stays blocked.
A* plans with 23 cm clearance, and path shortcuts are footprint checked.
The existing LiDAR-to-rover forward offset comes from the recorded teaching
pass; changing the sensor mount requires recalibration.

Turns require at least 30 cm measured sweep clearance. The controller watches
actual yaw progress, stops on reverse response or a stall, and limits each
turn to eight seconds. Short sensor/connection interruptions stop the wheels
and pause the mission. Recovery needs three continuous seconds of verified
inputs and a new clear route. Recovery expires after 30 seconds. **STOP AUTO**
cancels both active and paused missions; restarting a process forgets the goal.

Files: `mapping/amcl.yaml`, `mapping/auto_localization.py`,
`mapping/localization_quality.py`, `mapping/live_costmap.py`, and
`mapping/autonav_ros.py`. Status: `data/ros-map/localization-quality.json` and
`data/autonav/status.json`. Logs: `~/pitdivers_ros/logs/auto-c3c666243fd2/`.

Dependencies installed in WSL: `ros-lyrical-nav2-amcl`, `python3-scipy`.
Windows dashboard dependencies remain NumPy/SciPy. No new rover flash is
needed for these PC-side changes. The existing ESP signed-wheel endpoint and
600 ms command lease are used. Full Nav2 planning/controller servers are not
being claimed; planning and wheel control remain the project's Python node.

Validation on 29 September: 23 mapping tests passed, plus the nearby-start and
localization-view tests. They cover stale/misaligned scans, uncertainty, ray
clearing, endpoints, turns, recovery and cancellation. The live one-way trip
reached B after stopped recovery from data gaps. At verification, ROS reported
about 12 cm distance to B and 97% scan agreement; the ESP reported stopped.
The operator independently confirmed the physical rover reached B. Return
travel and in-place turning remain unverified on the floor.
# Turn progress update (29 September)

Turns now use fresh `odom -> base_link` yaw for measured progress; saved-map
corrections no longer count as wheel rotation. Timing starts after the first
acknowledged wheel command. A turn stops after two seconds with less than
0.015 rad of forward angular progress, after 15 seconds total, or after measured
wrong-way rotation. Motor duty remains 193, and scan, localization, clearance,
and firmware lease checks remain enabled. `data/autonav/status.json` includes a
`turn` diagnostic with elapsed time, rotation, odometry age and heading error.
The revised monitor passes automated tests; a physical turn retry is pending.

# Faster supervised demo profile

The active controller uses PWM 180 (previously 150), a 0.30 m arrival
tolerance (previously 0.22 m), and one second of continuously valid recovery
inputs (previously three). It steers while moving up to 0.65 rad heading error
(previously 0.50), retaining the 0.20 rad turn exit threshold. The angular
steering ratio is preserved at the higher duty. These are PWM settings, not a
calibrated speed in metres per second. Initial localization confirmation,
fresh-data limits, clearance checks and stop lease are unchanged. Status reports
the loaded settings under `drive_profile`. Physical validation at this higher
duty is pending.
