# PitDivers Camera + DHT11 firmware

This Arduino sketch combines the Freenove camera web server with the Freenove
DHT11 temperature/humidity example. Uploading this single sketch keeps both
features running on the same ESP32-S3.

## Connections

| DHT11 pin | ESP32-S3 |
|---|---|
| VCC | 3.3 V |
| DATA | GPIO 20 (add a 10 kΩ pull-up to 3.3 V if using a bare DHT11) |
| GND | GND |

GPIO 20 does not conflict with the camera pin map. It is also a native USB pin
on the ESP32-S3. This Freenove board normally uploads through its CH343 UART on
GPIO 43/44, but if USB/JTAG stops working, disconnect the DHT11 data lead while
uploading or move DATA to GPIO 21 and change `DHT_PIN` in the `.ino` file.

## Arduino setup

1. Install **DHTesp** from Arduino Library Manager.
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
| Temperature/humidity JSON | `http://<ip>:82/sensors` |
| Sensor service health | `http://<ip>:82/health` |

Example sensor response:

```json
{
  "ok": true,
  "sensor": "DHT11",
  "gpio": 20,
  "temperature_c": 23.4,
  "humidity_percent": 48.0,
  "status_code": 0,
  "age_ms": 127
}
```

The DHT11 is sampled every two seconds using `millis()`. There is no blocking
two-second `delay()`, so the camera server continues running independently.

## Source attribution

Camera server support files and the original DHT11 usage pattern are derived
from the Freenove Ultimate Starter Kit for ESP32-S3 examples. Project-specific
integration, JSON telemetry, error handling, and non-blocking scheduling are
maintained here.

The Freenove-derived files are distributed under CC BY-NC-SA 3.0. See
`FREENOVE_LICENSE.txt` in this folder before redistributing or using them.
