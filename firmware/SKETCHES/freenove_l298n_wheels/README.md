# Freenove ESP32-S3 wheel test

This sketch tests the existing L298N and four wheel motors. LiDAR and other sensors are not used.

| L298N input | Wire in the rover photos | Freenove ESP32-S3 pin |
|---|---|---|
| IN1 | Yellow | GPIO1 |
| IN2 | Green | GPIO2 |
| IN3 | Blue | GPIO41 |
| IN4 | Purple | GPIO42 |

Connect L298N GND to ESP32-S3 GND and the motor battery negative. Keep the motor battery positive on the L298N motor supply terminal. Power the ESP32-S3 from USB. Do not connect motor supply voltage to a GPIO.

Open `freenove_l298n_wheels.ino` in Arduino IDE. Choose **ESP32S3 Dev Module**, the board's COM port, 16 MB flash, and OPI PSRAM, then upload. Open Serial Monitor at 115200 baud. The sketch prints the web address. If home Wi-Fi is unavailable, connect to `PitDivers-Wheels` with password `rover1234`, then open `http://192.168.4.1/`.

Lift the chassis before testing. Hold a direction button to move and release it to stop. The motors also stop after 600 ms without another drive command. If a side runs backward, its motor-output wires or the corresponding control polarity need correcting.

The previous NodeMCU ESP8266 sketch is retained in `../rover_motion_control/`; it cannot run on this ESP32-S3. This wheel-test sketch does not control the LiDAR and has no controller or AI API.
