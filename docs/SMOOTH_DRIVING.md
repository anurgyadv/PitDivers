# Smooth demo driving

- Fresh IMU Z angular velocity, minus the current calibration bias, projects
  steering heading through at most 0.2 s of ROS pose age. Stale, tilted or invalid
  readings fall back to ROS heading. This is short-term steering prediction,
  not IMU fusion into AMCL or an independent XY position estimate.
- Route lookahead extends to 0.6 m only with a collision-checked segment through
  observed free space. Corners retain the shorter target when necessary.
- An established position can recover from a brief covariance/pose-update issue
  after five fresh good scans over at least one second. Bad wall agreement,
  pose corrections, relocalization and long gaps require full confirmation.
- The controller then requires 0.5 s of continuous healthy data before resuming.
- Straight duty increases from 180 to 200 only below 10 degrees heading error,
  with >=1.2 m live clearance, >=0.8 m remaining to the goal and a clear 0.6 m
  footprint segment. Turns and closer approaches stay at the existing duty.
- ESP obstacle checks, command leases, STOP and fresh localization gates remain.

No new firmware is needed. Software tests do not establish physical stopping
distance or prove improved mapping during driving; those require a supervised run.
