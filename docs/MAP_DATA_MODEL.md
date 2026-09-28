# Manual-run map data and mission format

PitDivers uses a metric 2D navigation map for teach-and-replay missions. The
Depth Anything GLB remains useful visual evidence, but it is not directly safe
or stable enough to act as the rover's navigation coordinate system.

## Expected output from a manual run

A processed manual run should eventually provide:

| Field | Meaning | Expected source |
|---|---|---|
| `teach_trace` | Timestamped rover poses (`x`, `y`, `yaw`) and localisation confidence | Wheel encoders + IMU, later corrected by VIO or fixed markers |
| `boundary` | Closed polygon defining the permitted operating area | Operator-drawn from the teach trace or surveyed points |
| `obstacles` | Closed polygons for machines, walls, drop-offs, and exclusion zones | Operator annotation, depth processing, or later SLAM |
| `width_m`, `height_m` | Metric map extent | Surveyed scale or calibrated trajectory |
| `frame_id` | Coordinate frame shared by map, rover pose, and route | Local mission origin, normally `map` |
| `source_capture` | Capture folder used to derive the map | Dashboard recording manifest |

The localisation output must be metric and share one stable origin. DA3 Base
depth is relative, so it cannot provide that scale by itself. Every estimated
pose should carry a confidence value so low-quality portions of a teach run can
be highlighted or rejected.

## Editable mission route

The map editor adds `route` waypoints. Each waypoint includes its metric
position, target speed, arrival tolerance, optional final heading, and zero or
more inspection actions. The server validates that waypoints remain within the
boundary and that route segments do not intersect obstacle polygons.

Saving a map writes `data/maps/<map-id>.json`. Compiling it produces a
controller-neutral plan containing `MOVE_TO` and inspection commands. The
motor controller is responsible for closing the loop using the live rover pose;
it must stop if localisation becomes stale, an obstacle appears, or the rover
leaves the permitted boundary.

## Safety boundary

The editor and compiled plan are mission-planning tools, not the final safety
layer. Hardware execution must still enforce an emergency stop, a watchdog,
live obstacle stopping, localisation freshness, maximum speed, and manual
operator override on the rover controller.
