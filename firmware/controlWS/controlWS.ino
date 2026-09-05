// controlWS.ino
// -----------------------------------------------------------------------------
// Pit Divers — WebSocket motor control plane for the ESP32-S3 WROOM.
//
// This is a STANDALONE sketch. It runs on the SAME ESP32-S3 as the camera
// firmware (PitDivers_Camera_DHT11), but in a separate flash slot. They do
// not run at the same time. Pick one with `esptool.py write_flash`.
//
// HARDWARE: L293D driven directly from the S3. Pin map matches the known-good
//           two-motor serial bench test:
//             Motor A: IN1=GPIO 1  IN2=GPIO 14  ENA=GPIO 41  (LEDC ch 2)
//             Motor B: IN3=GPIO 21 IN4=GPIO 47  ENB=GPIO 42  (LEDC ch 3)
//           A wiring summary also lives in this folder's README.md.
//
// NETWORK:
//   Port 80  -- (occupied) other service on this firmware
//   Port 81  -- (occupied) other service on this firmware
//   Port 82  -- (occupied) other service on this firmware
//   Port 83  -- plain HTTP. Serves the teleop UI (web/index.html).
//              Phone connects to http://192.168.4.1:83/ on the RoverPit AP.
//   Port 84  -- WebSocket. The UI connects to ws://192.168.4.1:84/.
//   Splitting HTTP/WS onto two ports is the simplest way to let the page be
//   served from PROGMEM while arduinoWebSockets owns its own TCP listener
//   (the library's WS upgrade handshake is hard to interleave with raw HTTP
//   on a single port). The phone never notices -- the page is loaded on :83
//   then JS opens :84.
//
// PROTOCOL: tiny text-only WebSocket on port 84.
//   Commands are single ASCII characters, one per WS message:
//     'F' = forward
//     'B' = reverse (backward)
//     'L' = turn left (pivot)
//     'R' = turn right (pivot)
//     'S' = stop
//     '0'..'9' = set speed 0..90% in 10% steps (sticky until changed)
//     '?' = status dump (text: state, speed, uptime, free heap)
//   Anything else = ignored (with a Serial log line).
//   Outgoing text frames:
//     "READY" / "BUSY" -- connect handshake
//     "SPEED=70"        -- ack of a '0'..'9' command
//     "STATE L=F R=B S=70% U=12s H=123456" -- status after each command
//
// SAFETY:
//   * Watchdog: if no command is received in 1500 ms, motors auto-stop.
//   * On connect, motors are stopped before the loop accepts commands.
//   * On disconnect, motors are stopped.
//   * Only one WS client at a time -- a second connect is dropped with "BUSY".
//   * The HTML UI holds a 250 ms heartbeat while a direction button is held,
//     so the firmware watchdog never trips on a healthy session.
//
// SERIAL: default UART (Serial.begin(115200)) — motors do not use UART0.
//
// NO CAMERA, NO SENSORS, NO WIFI STATION MODE — this sketch is AP-only,
// serves an open SSID "RoverPit" (same as camera firmware for workshop UX).
// -----------------------------------------------------------------------------

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <WebSocketsServer.h>  // https://github.com/Links2004/arduinoWebSockets
#include "motors_direct.h"
#include "web/index_html.h"     // the teleop UI, compiled in from web/index.html

// ---------------------------------------------------------------------------
// AP credentials. secrets.h is git-ignored and optional; if it is not present
// the rover comes up as an OPEN AP named "RoverPit" (ideal for a quick bench
// test). To lock the AP down, copy secrets.example.h to secrets.h and set
// AP_SSID / AP_PASS there. Both are string-literal #defines.
// ---------------------------------------------------------------------------
#if __has_include("secrets.h")
#include "secrets.h"
#endif
#ifndef AP_SSID
#define AP_SSID "RoverPit"
#endif
#ifndef AP_PASS
#define AP_PASS ""            // empty = open AP (no password)
#endif

// ---------------------------------------------------------------------------
// HTTP server (port 83) — serves the teleop UI from PROGMEM. See the header
// comment for why we split this from the WebSocket port. (Ports 80/81/82 are
// already used by other services on this firmware.)
// ---------------------------------------------------------------------------
WebServer http(83);

// ---------------------------------------------------------------------------
// WebSocket server (port 84) — sits on top of the standard WiFiServer.
// arduinoWebSockets handles the upgrade handshake and frames for us.
// ---------------------------------------------------------------------------
WebSocketsServer ws = WebSocketsServer(84);

static const uint32_t WATCHDOG_MS = 1500;
static uint32_t _lastCommandMs    = 0;
static uint8_t  _speedPct         = 70;   // default speed; sticky across commands
static bool     _wsConnected      = false;
static uint8_t  _clientId         = 0xFF; // 0xFF = none

// ---------------------------------------------------------------------------
// Forward declarations
// ---------------------------------------------------------------------------
void onWsEvent(uint8_t num, WStype_t type, uint8_t* payload, size_t length);
void handleCommand(char c);
void sendStatus(uint8_t num);
void checkWatchdog();
void handleHttpRoot();
void handleHttpNotFound();

// ---------------------------------------------------------------------------
// WiFi event — useful for debugging "why did the rover drop off the network"
// ---------------------------------------------------------------------------
void onWifiEvent(WiFiEvent_t event) {
    switch (event) {
        case ARDUINO_EVENT_WIFI_AP_START:
            Serial.println("[wifi] AP started -- SSID=" AP_SSID);
            break;
        case ARDUINO_EVENT_WIFI_AP_STACONNECTED:
            Serial.println("[wifi] station connected to AP");
            break;
        case ARDUINO_EVENT_WIFI_AP_STADISCONNECTED:
            Serial.println("[wifi] station disconnected from AP -- motors will auto-stop");
            motors.stop();
            _wsConnected = false;
            _clientId    = 0xFF;
            break;
        default:
            break;
    }
}

// ---------------------------------------------------------------------------
// WebSocket event handler
// ---------------------------------------------------------------------------
void onWsEvent(uint8_t num, WStype_t type, uint8_t* payload, size_t length)
{
    switch (type) {
        case WStype_CONNECTED: {
            IPAddress ip = ws.remoteIP(num);
            Serial.printf("[ws ] client %u connected from %s\n", num, ip.toString().c_str());

            // Refuse a second client — single-driver workshop UX.
            if (_wsConnected) {
                Serial.println("[ws ] already have a client -- dropping new one");
                ws.sendTXT(num, "BUSY");
                ws.disconnect(num);
                return;
            }
            _wsConnected = true;
            _clientId    = num;
            _lastCommandMs = millis();
            motors.stop();  // safe start
            ws.sendTXT(num, "READY");
            break;
        }

        case WStype_DISCONNECTED: {
            Serial.printf("[ws ] client %u disconnected\n", num);
            if (num == _clientId) {
                _wsConnected = false;
                _clientId    = 0xFF;
                motors.stop();
            }
            break;
        }

        case WStype_TEXT: {
            // Treat the first byte as the command. Extra bytes ignored.
            if (length == 0) return;
            char c = (char)payload[0];
            handleCommand(c);
            _lastCommandMs = millis();
            break;
        }

        case WStype_BIN:
            // Binary frames not supported in this revision.
            Serial.printf("[ws ] binary frame from client %u (len=%u) -- ignored\n", num, (unsigned)length);
            break;
        case WStype_FRAGMENT_TEXT_START:
        case WStype_FRAGMENT_BIN_START:
        case WStype_FRAGMENT:
        case WStype_FRAGMENT_FIN:
            // Fragmented frames not supported. Reject to avoid state drift.
            Serial.printf("[ws ] fragmented frame from client %u -- disconnecting\n", num);
            ws.disconnect(num);
            break;
        case WStype_PING:
        case WStype_PONG:
            // Library handles these automatically; no action needed.
            break;
        default:
            Serial.printf("[ws ] unhandled event type=%d len=%u\n", (int)type, (unsigned)length);
            break;
    }
}

// ---------------------------------------------------------------------------
// Command handler
// ---------------------------------------------------------------------------
void handleCommand(char c)
{
    // Speed presets 0..9
    if (c >= '0' && c <= '9') {
        uint8_t pct = (c - '0') * 10;   // '1' -> 10, '9' -> 90
        if (c == '0') pct = 0;
        _speedPct = pct;
        // The next F/B/L/R will use the new speed. We do not re-issue the
        // last direction here, because we don't track it — safer to require
        // an explicit motion command. The client UI should mirror this.
        Serial.printf("[cmd] speed set to %u%%\n", _speedPct);
        ws.sendTXT(_clientId, String("SPEED=") + _speedPct);
        return;
    }

    switch (c) {
        case 'F': case 'f':
            motors.forward(_speedPct);
            Serial.printf("[cmd] FORWARD speed=%u\n", _speedPct);
            break;
        case 'B': case 'b':
            motors.backward(_speedPct);
            Serial.printf("[cmd] REVERSE speed=%u\n", _speedPct);
            break;
        case 'L': case 'l':
            motors.turnLeft(_speedPct);
            Serial.printf("[cmd] LEFT    speed=%u\n", _speedPct);
            break;
        case 'R': case 'r':
            motors.turnRight(_speedPct);
            Serial.printf("[cmd] RIGHT   speed=%u\n", _speedPct);
            break;
        case 'S': case 's':
            motors.stop();
            Serial.println("[cmd] STOP");
            break;
        case '?':
            sendStatus(_clientId);
            break;
        default:
            Serial.printf("[cmd] unknown '%c' (0x%02X) -- ignored\n", c, (uint8_t)c);
            ws.sendTXT(_clientId, String("ERR?") + c);
            return;
    }

    // Echo the new state to the client
    sendStatus(_clientId);
}

// ---------------------------------------------------------------------------
// Status dump (text). Kept tiny so a phone WS client can render it.
// ---------------------------------------------------------------------------
void sendStatus(uint8_t num)
{
    if (num == 0xFF) return;
    String s = "STATE ";
    s += "L=";
    switch (motors.leftDirection()) {
        case DIR_STOP:    s += "S"; break;
        case DIR_FORWARD: s += "F"; break;
        case DIR_REVERSE: s += "R"; break;
    }
    s += " R=";
    switch (motors.rightDirection()) {
        case DIR_STOP:    s += "S"; break;
        case DIR_FORWARD: s += "F"; break;
        case DIR_REVERSE: s += "R"; break;
    }
    s += " S=";
    s += _speedPct;
    s += "% U=";
    s += (millis() / 1000);
    s += "s H=";
    s += ESP.getFreeHeap();
    ws.sendTXT(num, s);
}

// ---------------------------------------------------------------------------
// Watchdog: if no command in 1.5s, stop the motors. The rover does not
// ghost-drive if the phone drops the WS.
// ---------------------------------------------------------------------------
void checkWatchdog()
{
    if (!_wsConnected) return;
    if (motors.leftDirection() == DIR_STOP && motors.rightDirection() == DIR_STOP) {
        // already stopped, no need to spam Serial
        return;
    }
    uint32_t now = millis();
    if (now - _lastCommandMs > WATCHDOG_MS) {
        Serial.printf("[wdog] no command in %u ms -- stopping\n", WATCHDOG_MS);
        motors.stop();
    }
}

// ---------------------------------------------------------------------------
// HTTP handlers — the only thing we serve is the teleop UI from PROGMEM. Any
// other path gets a 404. We don't set CORS headers because the page is always
// served from this same AP -- no cross-origin case to worry about.
// ---------------------------------------------------------------------------
void handleHttpRoot()
{
    // send_P reads directly from PROGMEM into the TCP send buffer, so the
    // payload never has to be copied onto the heap first.
    Serial.printf("[http] serving / (%u bytes)\n", (unsigned)INDEX_HTML_LEN);
    http.send_P(200, "text/html; charset=utf-8", INDEX_HTML, INDEX_HTML_LEN);
}

void handleHttpNotFound()
{
    http.send(404, "text/plain",
        "PitDivers controlWS -- not found.\n"
        "Connect a WebSocket to port 84 to drive the rover.\n");
}

// ---------------------------------------------------------------------------
// setup / loop
// ---------------------------------------------------------------------------
void setup()
{
    // Motors do not use UART0 (43/44), so the default UART serial is free —
    // same as the working serial bench test.
    Serial.begin(115200);
    delay(300);  // serial settle

    Serial.println();
    Serial.println("=================================================");
    Serial.println(" Pit Divers -- controlWS (WebSocket motor driver)");
    Serial.println("=================================================");
    Serial.println("Pin map (matches the working serial bench test):");
    Serial.println("  L293D IN1=GPIO 1   IN2=GPIO 14  ENA=GPIO 41");
    Serial.println("  L293D IN3=GPIO 21  IN4=GPIO 47  ENB=GPIO 42");
    Serial.println("PWM: LEDC ch 2/3, 1 kHz, 11-bit (max 2047)");
    Serial.println("Watchdog: 1500 ms auto-stop");
    Serial.println();

    // WiFi — AP only, same SSID as the camera firmware for workshop UX.
    WiFi.onEvent(onWifiEvent);
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASS);   // AP_PASS may be empty for an open AP
    Serial.print("[wifi] AP IP: "); Serial.println(WiFi.softAPIP());

    // Motors — start in a safe state
    motors.begin();
    motors.stop();

    // HTTP — serve the teleop UI from PROGMEM on port 83
    http.on("/", HTTP_GET, handleHttpRoot);
    http.onNotFound(handleHttpNotFound);
    http.begin();
    Serial.println("[http] serving teleop UI on http://" + WiFi.softAPIP().toString() + ":83/");

    // WebSocket — control plane on port 84
    ws.begin();
    ws.onEvent(onWsEvent);
    Serial.println("[ws   ] listening on ws://" + WiFi.softAPIP().toString() + ":84/");
}

void loop()
{
    ws.loop();            // service WebSocket frames
    http.handleClient();  // service any pending HTTP requests
    checkWatchdog();      // stop motors if the client went silent
    delay(5);             // small yield; arduinoWebSockets is not RTOS-driven
}
