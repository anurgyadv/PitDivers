# Freenove wheels and LDS02RR LiDAR test

This standalone ESP32-S3 sketch retains the L298N wheel connections from the wheel-only sketch: yellow IN1 → GPIO1, green IN2 → GPIO2, blue IN3 → GPIO41, purple IN4 → GPIO42.

## LiDAR connections

| LiDAR / driver connection | Freenove ESP32-S3 |
|---|---|
| LDS02RR pad 2 TX, confirmed 3.3 V signal | GPIO14 (UART RX) |
| MOSFET driver gate/control input | GPIO47 (PWM output) |
| LiDAR pad 7 GND and driver GND | GND, shared with L298N and supply negative |
| LiDAR pad 12 VCC and scan motor M+ | Regulated 5 V supply |
| Scan motor M− | MOSFET driver's switched motor terminal |

Do not connect the scan motor to any ESP32 GPIO. Keep the LiDAR motor off until the supply, polarity, and MOSFET driver connections have been checked. The previous NodeMCU D7/D0 pin numbers do not apply here. No echo voltage divider is used on GPIO14; the LiDAR TX must be 3.3 V compatible.

Open `freenove_wheels_lidar.ino` in Arduino IDE and select **ESP32S3 Dev Module**, 16 MB flash, OPI PSRAM, and the Freenove COM port. Upload, then open Serial Monitor at 115200 baud for the web address. Home Wi-Fi settings are in the local ignored `secrets.h`. If home Wi-Fi is unavailable, connect to `PitDivers-Wheels` with password `rover1234` and open `http://192.168.4.1/`.

The LiDAR motor remains off at boot. On the web page, press **Start LiDAR** and watch valid packet count and RPM. `/api/lidar/status` returns live counters; `/api/lidar/scan` returns 360 distance values in millimetres. The motor automatically stops after five seconds without a valid packet. Press **Stop LiDAR** when finished. Keep the chassis lifted for the first wheel test.
