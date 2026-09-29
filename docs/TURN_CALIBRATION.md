# Surface turn calibration

The demo's **Calibrate turns** button requires the updated
`firmware/SKETCHES/freenove_room_mapping` firmware. Older firmware produces an
explicit update-required message. No automatic flash or test motion occurs.

1. Place the rover on the actual surface, level, with at least 45 cm clearance
   around the LiDAR. Stop any mission. Keep the dashboard visible.
2. Press **Calibrate turns** and confirm the displayed motion description.
3. Remain stationary for three seconds. The rover then commands full duty 255
   for up to 30 measured degrees left, settles for 700 ms, and measures right.
4. Read the saved left/right rates in degrees per second. STOP cancels. Each
   powered turn is limited to 2.5 seconds. Exact return to its starting heading
   is not guaranteed because of motor coast and gyro error.

The firmware measures stationary gyro bias, checks variance, samples at a
nominal 100 Hz, and rejects gaps over 100 ms, saturation and a nonvertical IMU
Z axis. Its left turn establishes gyro polarity; the right turn must have
opposite polarity. This does not independently verify physical left/right
wiring, gyro scale accuracy, or absolute compass heading.

During the stationary bias phase, absolute Z acceleration must stay within
0.85–1.15 g. During the turn/settling phases, moderate departures must persist
for 150 ms before aborting; this tolerates brief motor-start vibration.
Readings outside 0.5–1.5 g abort immediately. This is an acceleration check,
not a direct measurement of tilt angle.

Fresh LiDAR (<350 ms), at least 180 valid returns, all valid ranges >=450 mm,
working IMU and a browser heartbeat (<1.5 seconds) are required throughout.
Wi-Fi loss, STOP and manual watchdog handling cancel calibration. Concurrent
wheel commands are rejected. Switching tabs cancels the initiating browser's
test. Raw scans enter an asynchronous SD queue while the control task continues;
log downloads pause during the test. Queue overflow is reported explicitly. Temperature/humidity
sampling resumes afterward.

Successful bias, polarity and full-power left/right rates persist in ESP NVS.
A failed repeat retains the prior valid profile. Bias must be remeasured after
reboot/temperature changes before using it for a new gyro-controlled maneuver.

The onboard-motion firmware consumes the calibration for gyro-controlled turns
and heading-hold steering. The ROS navigator detects this firmware automatically;
older firmware continues to use ROS turn feedback. See ONBOARD_MOTION.md for
build, upload, task separation and operating limits.
