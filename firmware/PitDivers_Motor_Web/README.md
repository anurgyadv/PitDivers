# PitDivers four-motor web test

This standalone ESP32-S3 firmware serves a phone-friendly arrow controller and
tests four motors through one 74HC595 and two L293D drivers. It does not start
the camera or sensors; they may remain connected on their reserved GPIOs.

## Final motor-control wiring

| ESP32-S3 GPIO | Connection |
|---:|---|
| 1 | 74HC595 DATA / SER pin 14 |
| 2 | 74HC595 CLOCK / SRCLK pin 11 |
| 48 | 74HC595 LATCH / RCLK pin 12 |
| 19 | Pin 1 / EN1 on both L293Ds for the left motors |
| 20 | Pin 9 / EN2 on both L293Ds for the right motors |

The 74HC595 outputs are Q0/Q1 for front-left, Q2/Q3 for front-right,
Q4/Q5 for rear-left, and Q6/Q7 for rear-right. Follow
`docs/wiring/FINAL_GPIO_MAP.md` for the complete IC and motor connections.

## Upload and test

1. Install **WebSockets by Markus Sattler** from Arduino Library Manager.
2. Copy `secrets.example.h` to `secrets.h` and enter the home Wi-Fi name and password.
3. Open `PitDivers_Motor_Web.ino` in Arduino IDE.
4. Select **ESP32S3 Dev Module**, enable USB CDC on boot, and upload.
5. Keep the controller on the same home Wi-Fi and open the numeric address shown in Serial Monitor. You can also try **http://pitdivers.local/**.
6. Lift the chassis, then use FL, FR, RL and RR to verify each wheel before testing forward, reverse and pivots.

Drag the joystick in any direction to mix the left and right motor speeds. Up
and down drive straight, left and right pivot, and diagonal positions make
smooth forward or reverse arcs. Releasing it stops the rover. The firmware also stops
the motors after 1.5 seconds without a drive command or when the WebSocket
disconnects.

The drive-level control maps 0–100% on screen to 60–100% PWM while a movement
button is held. STOP still sends 0% PWM. This avoids the motors' observed dead
zone below about 60%; it does not make 60% electrical PWM equal zero power.

The live graph displays the signed PWM command sent to each side: positive is
forward and negative is reverse. The ESP32 and L293D have no motor-current sense
connection, so the firmware cannot measure electrical power, current, battery
voltage, motor speed or mechanical output. Actual current requires an added
current sensor or shunt and an ESP32 ADC input.

The firmware reverses the logical right side because the right motors are
mirrored on the chassis. If both right motors run the wrong way after this
update, change `INVERT_RIGHT_SIDE` in `motor_control.cpp` to `false`.

GPIO48 drives the 74HC595 latch and the board's built-in RGB LED. Brief white or
red flashes are therefore expected whenever direction data is latched. Do not
run separate RGB LED code on GPIO48 with this wiring.

If only one wheel rotates the wrong way, switch that motor's two output wires.
If RR remains intermittent during its individual test, inspect 74HC595 Q6/Q7,
rear L293D pins 10/15 and 11/14, the shared GPIO20 enable, and its motor/output
wires. Test with the chassis lifted before placing it on the ground.
