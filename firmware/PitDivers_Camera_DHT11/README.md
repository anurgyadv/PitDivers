# PitDivers Camera + DHT11 + HC-SR04 firmware

This Arduino sketch combines the Freenove camera web server with the Freenove
DHT11 temperature/humidity and ultrasonic examples. Uploading this single
sketch keeps the camera and both sensors running on the same ESP32-S3.

## Connections

| DHT11 pin | ESP32-S3 |
|---|---|
| VCC | 3.3 V |
| DATA | GPIO 21 (add a 10 kΩ pull-up to 3.3 V if using a bare DHT11) |
| GND | GND |

| HC-SR04 pin | ESP32-S3 |
|---|---|
| VCC | 5 V |
| TRIG | GPIO 46 |
| ECHO | GPIO 14 through a voltage divider |
| GND | GND |

| MPU6050 pin | ESP32-S3 |
|---|---|
| VCC | 5 V (Freenove breakout module) |
| GND | GND |
| SDA | GPIO 41 |
| SCL | GPIO 42 |
| AD0 | Leave LOW/unconnected for address `0x68` |
| INT, XDA, XCL | Not connected |

**Do not connect HC-SR04 ECHO directly to the ESP32-S3.** ECHO is a 5 V signal
and ESP32 GPIO is 3.3 V only. Use a divider such as:

```text
HC-SR04 ECHO ── 1 kΩ ──┬── GPIO 14
                        └── 2 kΩ ── GND
```

GPIO 46 and GPIO 14 do not conflict with the selected camera map. GPIO 46 can
operate as an output, but it is also a boot-strapping pin. The HC-SR04 TRIG
input should leave it LOW during reset. If flashing or booting becomes
unreliable, temporarily disconnect the TRIG wire during reset/upload.

## Arduino setup

1. Install **DHTesp** and **MPU6050_tockn** from Arduino Library Manager.
2. Open the local `secrets.h` file and enter the rover Wi-Fi credentials.
   It is ignored by Git; `secrets.example.h` is the safe version committed to
   the repository.
3. Open `PitDivers_Camera_DHT11.ino` in Arduino IDE.
4. Use the same FNK0082 settings as the working camera sketch:
   - Board: ESP32S3 Dev Module
   - CPU: 240 MHz
   - Flash mode: QIO 80 MHz
   - Flash size: 8 MB
   - Partition scheme: Default 4 MB with SPIFFS
   - PSRAM: OPI PSRAM
5. Compile and upload.
6. Open Serial Monitor at 115200 baud. The firmware prints all three URLs.

## Endpoints

Replace `<ip>` with the address printed in Serial Monitor.

| Feature | URL |
|---|---|
| Camera controls | `http://<ip>/` |
| MJPEG stream | `http://<ip>:81/stream` |
| DHT11 and ultrasonic JSON | `http://<ip>:82/sensors` |
| Sensor service health | `http://<ip>:82/health` |

Example sensor response:

```json
{
  "ok": true,
  "sensor": "DHT11",
  "dht_ok": true,
  "gpio": 21,
  "temperature_c": 23.4,
  "humidity_percent": 48.0,
  "status_code": 0,
  "age_ms": 127,
  "sonar_ok": true,
  "distance_cm": 83.4,
  "sonar_trig_gpio": 46,
  "sonar_echo_gpio": 14,
  "sonar_age_ms": 72,
  "mpu_ok": true,
  "mpu_address": "0x68",
  "mpu_sda_gpio": 41,
  "mpu_scl_gpio": 42,
  "accel_g": {"x": 0.012, "y": -0.025, "z": 0.998},
  "gyro_dps": {"x": 0.14, "y": -0.08, "z": 0.03},
  "tilt_deg": {"roll": -1.4, "pitch": 0.7, "yaw": 0.1},
  "mpu_temperature_c": 27.6,
  "mpu_age_ms": 18
}
```

The DHT11 is sampled every two seconds and the HC-SR04 every 100 ms using
`millis()` scheduling. An ultrasonic timeout is capped at 42 ms; the camera
stream servers run in their own tasks and there is no continuously blocking
sensor loop.

The MPU6050 is updated every 50 ms (20 Hz). At startup, keep the rover still
while `MPU6050_tockn` calculates gyro offsets. Acceleration is reported in g,
angular rate in degrees per second, and roll/pitch/yaw in degrees.

The camera uses a 20 MHz XCLK, two PSRAM frame buffers, and latest-frame
capture. This module falls back to RGB565, so the web server converts its frames
to JPEG in software at quality 70 instead of the original 80. That reduces CPU
time and network payload without reducing the configured SVGA resolution. If a
particular replacement camera module proves unstable at 20 MHz, set
`CAMERA_XCLK_HZ` back to `10000000`.

## Source attribution

Camera server support files and the original DHT11/ultrasonic usage patterns
are derived from the Freenove Ultimate Starter Kit for ESP32-S3 examples.
Project-specific integration, JSON telemetry, error handling, and periodic
scheduling are maintained here.

The Freenove-derived files are distributed under CC BY-NC-SA 3.0. See
`FREENOVE_LICENSE.txt` in this folder before redistributing or using them.
