# Wheel controller + LDS02RR LiDAR test

The original wheel sketch was copied to
`../rover_motion_control_backup_2026-09-27/rover_motion_control_backup_2026-09-27.ino`
before this integration. Its D1, D2, D5 and D6 wheel pins remain unchanged.

## Connections for this firmware

| Function | NodeMCU ESP8266 |
|---|---|
| Wheel driver IN1, IN2, IN3, IN4 | D1, D2, D5, D6 (unchanged) |
| LDS02RR TX, after confirming it is a 3.3 V signal | D7 / GPIO13 |
| 3.3 V-compatible MOSFET driver control input | D0 / GPIO16 |
| LiDAR supply negative and motor-driver ground | NodeMCU GND, common with the wheel-driver ground |
| LiDAR electronics VCC and spin-motor positive | Separate regulated 5 V supply |
| Spin-motor negative | MOSFET driver's switched output |

The LiDAR motor must not connect directly to D0. The IRF520N in the previous
diagram has no verified low-resistance specification at a 3.3 V gate drive;
use a driver specified for 3.3 V input. Do not feed LiDAR 5 V from the
NodeMCU 3V3 pin or the rover's wheel-battery voltage. Verify the LiDAR's
actual TX, VCC, ground and motor contacts before applying power; wire color
alone is insufficient.

This uses the ESP8266 hardware UART remapped to D7 for RX. D8 becomes UART TX
but has no wire in this setup. Startup messages still appear over USB before
the remap, while scan data and status are shown on the web page thereafter.

## Test

1. Upload `rover_motion_control.ino` with the **NodeMCU 1.0 (ESP-12E Module)**
   board selected. Keep the wheels lifted during the first test.
2. Open the rover control page at the IP shown in the 115200-baud Serial
   Monitor during startup, or join its fallback `PitdiversRover` hotspot.
3. Confirm the wheel controls still respond and stop when released.
4. Press **LiDAR Start**. The page shows RPM, PWM, valid and bad packet
   counts, and how many of 360 angle bins contain a distance. You can also
   open `/api/lidar/status` and `/api/lidar/scan` at the rover IP.
5. Press **LiDAR Stop** before rewiring. If no valid scan arrives for five
   seconds, the firmware switches off its motor-control output automatically.

This is a first bench test, not a claim that the LiDAR motor driver, pin
identity, power source or full scan performance has been validated.
