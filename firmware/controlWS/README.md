# PitDivers controlWS — WebSocket wheel-drive firmware

A **standalone**, wheels-only firmware for the PitDivers ESP32-S3 rover. It does
one thing: bring up a Wi-Fi access point, serve a phone teleop page, and drive
the two DC gear motors (through an L293D) over a tiny WebSocket protocol.

There is **no camera, no DHT11/sonar/MPU, and no Wi-Fi station mode** here — this
is the minimal build for a drive test. It is a separate sketch from
`firmware/PitDivers_Camera_DHT11/`; only one firmware runs on the board at a
time (flash whichever one you want to test).

## What you get

- Boots as an **open access point** named `RoverPit` (`192.168.4.1`).
- Serves the teleop UI at **`http://192.168.4.1:83/`**.
- Drives the motors over a WebSocket on **`ws://192.168.4.1:84/`**.
- **Safety watchdog:** if no command arrives for 1.5 s the motors auto-stop, so
  a dropped phone connection halts the rover. The UI holds the connection alive
  with a 250 ms heartbeat while a button is pressed.

## Wiring — L293D driven directly from the S3

This pin map matches the known-good two-motor L293D serial bench test.

| L293D pin | Function | ESP32-S3 GPIO | Notes |
|---|---|---|---|
| IN1 | Motor A direction 1 | **GPIO 1** | |
| IN2 | Motor A direction 2 | **GPIO 14** | |
| ENA | Motor A PWM enable | **GPIO 41** | LEDC channel 2 |
| IN3 | Motor B direction 1 | **GPIO 21** | |
| IN4 | Motor B direction 2 | **GPIO 47** | |
| ENB | Motor B PWM enable | **GPIO 42** | LEDC channel 3 |

Motor power (the L293D **Vs / motor-supply** pin) comes from the battery/motor
rail, **not** the S3's 3.3 V. Tie the L293D and ESP32-S3 grounds together. The
L293D logic pin (Vss) goes to 5 V/3.3 V logic as per your board.

These pins leave UART0 (43/44) free, so **serial debug uses the default UART**
(`Serial.begin(115200)`) — the same Serial Monitor you used for the bench test.

PWM is LEDC at **1 kHz, 11-bit** (max duty 2047). Channels 0 and 1 are left free
for the camera build's XCLK timer; this sketch uses channels 2 and 3.

> If your wiring differs, change the pin constants at the top of
> `motors_direct.cpp` — that is the single source of truth for the pin map.

## Libraries

Install once from the Arduino Library Manager (or `arduino-cli lib install`):

- **arduinoWebSockets** by Markus Sattler — <https://github.com/Links2004/arduinoWebSockets>

`WiFi` and `WebServer` ship with the ESP32 Arduino core. This sketch targets
**ESP32 Arduino core 3.x** (it uses `ledcAttachChannel()` / `ledcWrite(pin, …)`).

## Build & flash (Arduino IDE)

1. (Optional) To secure the AP, copy `secrets.example.h` to `secrets.h` and set
   `AP_SSID` / `AP_PASS`. Skip this and you get the open `RoverPit` AP.
2. Open `controlWS.ino`.
3. Board settings (same board as the camera build):
   - Board: **ESP32S3 Dev Module**
   - CPU: 240 MHz · Flash: QIO 80 MHz · Flash size: 8 MB
   - Partition scheme: Default 4 MB with SPIFFS
   - PSRAM: OPI PSRAM
4. Compile and upload. Open Serial Monitor at 115200 baud; it prints the AP IP
   and both URLs.

## Drive it

1. On your phone, join the **`RoverPit`** Wi-Fi network.
2. Open **`http://192.168.4.1:83/`** in a browser.
3. Hold a direction arrow to drive; release (or tap **STOP**) to halt. Drag the
   speed slider (0–90 %). On a laptop you can also use **W/A/S/D** or the arrow
   keys, and **Space** to stop.

## WebSocket protocol (port 84)

Single-character text messages, one command per frame:

| Send | Meaning |
|---|---|
| `F` / `B` | forward / reverse (both wheels) |
| `L` / `R` | turn left / right (pivot: one wheel drives) |
| `S` | stop |
| `0`–`9` | set speed to 0–90 % (10 % steps, sticky until changed) |
| `?` | request a status dump |

The firmware replies with text frames: `READY` / `BUSY` on connect, `SPEED=70`
after a speed change, and `STATE L=F R=F S=70% U=12s H=123456` after each
command (left dir, right dir, speed, uptime seconds, free heap).

Only one client may drive at a time; a second connection is refused with `BUSY`.

## Editing the UI

The page is authored in `web/index.html` and compiled into the firmware as a
PROGMEM string in `web/index_html.h`. After editing the HTML, regenerate the
header:

```bash
cd firmware/controlWS
python3 tools/gen_index_html.py
```

Then rebuild the sketch.
