# Room demo

Open http://127.0.0.1:8768/ (the older dashboard/collector remains on 8767).
After a PC restart, run `powershell -File mapping/start_demo.ps1` from this project.

1. **Scan:** Start new room scan. Wait for the map, then hold the arrow buttons
   to drive slowly; release to stop. Revisit the start when practical. Press
   Finish scan & use map and keep the rover stationary during localization.
2. **Mark:** Click one to six destinations in scanned open floor. Points need
   enough space for the rover footprint. Find best route previews the visiting
   order. Walls, disconnected floor and unknown space are rejected.
3. **Run:** Leave Return to trip start checked and press Go & return. The return
   point is where the rover starts this trip, not the original scan origin.
   STOP cancels travel, including paused recovery. Stay beside the rover.

The planner uses A* with a 23 cm clearance radius, then an exhaustive shortest
tour search for up to six stops using grid-path distances. It smooths only through
clear cells. The controller revalidates the route from its actual position when
Go is pressed and replans locally following data recovery. This is a grid-distance
optimum, not a claim about minimum real travel time or perfect localization.

The arrow uses the calibrated 2.936 rad chassis/LiDAR mounting offset. LiDAR scan
coordinates are not rotated by this display correction. Automatic turn duty is
255/255; translation is 180/255. Fresh-scan, localization, clearance and measured
turn-progress stops remain enabled. No firmware flash is needed.

Temperature/humidity cards and map layers remain. Environmental colours represent
measurements at the rover's locations, not an inferred temperature for every wall.
Raw SD records and locally saved maps remain separate from route previews.

ROS mode changes are owned by `demo_stack.py`. Do not run another mapping or
localization launcher concurrently. Logs are in `data/demo` and
`~/pitdivers_ros/logs`. Initial AMCL pose comes from the freshly completed map;
scan agreement and uncertainty checks must pass before driving.

Automated planner and sequence tests use no motors. A physical multi-stop tour
and full-power turns still require a supervised test on this floor.

Verification: 29 Windows unit tests passed (one ROS-only test skipped); the ROS
sequence test passed separately in WSL. Stationary scan/freeze/localize, live pose,
environment telemetry and a free-floor return-route preview were exercised live.
The stationary test map is not a complete room survey.
