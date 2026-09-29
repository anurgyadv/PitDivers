/*
  Pitdivers Rover - Motion Controller + LDS02RR LiDAR (NodeMCU ESP8266)
  ----------------------------------------------------------------
  HUMAN mode: hold-to-drive web controls.
  CONTROLLER mode: a PC gamepad bridge sends signed tank-drive values.
  AI mode: authenticated, time-bounded HTTP commands.
  Every movement has a lease, so stale commands stop automatically.

  Wiring:
    L298N IN1 -> D1/GPIO5; IN2 -> D2/GPIO4
    L298N IN3 -> D5/GPIO14; IN4 -> D6/GPIO12
    LiDAR TX (confirmed 3.3V) -> D7/GPIO13 (hardware UART RX after Serial.swap)
    3.3V-compatible MOSFET driver IN -> D0/GPIO16 (LiDAR motor PWM)
    LiDAR and driver ground -> NodeMCU GND; LiDAR gets regulated 5V
    Do not connect the LiDAR motor directly to any NodeMCU pin.
    L298N GND -> NodeMCU GND and battery negative
    Motor battery positive -> L298N +12V input
    Leave L298N +5V disconnected; power NodeMCU separately by USB.
*/

#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <string.h>

const char* ssid = "OPTUS_B4E198N";
const char* password = "oaten72367rt";

// Change before controller or AI use. Bridges send this value in X-API-Key.
const char* controlApiKey = "RANDOMKEY";

const int IN1 = 5;
const int IN2 = 4;
const int IN3 = 14;
const int IN4 = 12;
const int LIDAR_PWM_PIN = 16; // D0; wheel pins above stay unchanged
const int LIDAR_RX_PIN = 13;  // D7; Serial.swap() maps UART0 RX here
const int LIDAR_TARGET_RPM = 300;
const unsigned long LIDAR_PACKET_TIMEOUT_MS = 5000;

uint16_t lidarDistanceMm[360] = {};
uint8_t lidarPacket[22] = {};
uint8_t lidarPacketPos = 0;
bool lidarRunning = false;
int lidarPwm = 0;
float lidarRpm = 0;
unsigned long lidarGoodPackets = 0;
unsigned long lidarBadPackets = 0;
unsigned long lidarLastGoodMs = 0;
const char* lidarFault = "stopped";

ESP8266WebServer server(80);
bool usingFallbackAP = false;
unsigned long lastReconnectCheck = 0;

enum ControlMode { MODE_HUMAN, MODE_CONTROLLER, MODE_AI };
enum MotionState {
  MOTION_STOPPED, MOTION_FORWARD, MOTION_BACKWARD, MOTION_LEFT, MOTION_RIGHT
};

ControlMode controlMode = MODE_HUMAN;
MotionState motionState = MOTION_STOPPED;
bool motionLeaseActive = false;
unsigned long motionDeadline = 0;

const unsigned long HUMAN_LEASE_MS = 650;
const unsigned long CONTROLLER_LEASE_MS = 350;
const unsigned long MAX_AI_DURATION_MS = 2000;
int currentSpeed = 140;

void motorA(bool forward, int pwmValue) {
  analogWrite(IN1, forward ? pwmValue : 0);
  analogWrite(IN2, forward ? 0 : pwmValue);
}

void motorB(bool forward, int pwmValue) {
  analogWrite(IN3, forward ? pwmValue : 0);
  analogWrite(IN4, forward ? 0 : pwmValue);
}

void stopAll() {
  analogWrite(IN1, 0);
  analogWrite(IN2, 0);
  analogWrite(IN3, 0);
  analogWrite(IN4, 0);
  motionState = MOTION_STOPPED;
  motionLeaseActive = false;
}

// The LDS02RR sends 22-byte packets: header, angle, speed, four samples,
// then a two-byte checksum. This is adapted from the user's Uno scan test.
bool lidarChecksumOK(const uint8_t* packet) {
  uint32_t sum = 0;
  for (int i = 0; i < 10; ++i) {
    const uint16_t word = packet[i * 2] | (uint16_t(packet[i * 2 + 1]) << 8);
    sum = (sum << 1) + word;
  }
  sum = ((sum & 0x7FFF) + (sum >> 15)) & 0x7FFF;
  const uint16_t expected = packet[20] | (uint16_t(packet[21]) << 8);
  return sum == expected;
}

void stopLidar(const char* reason) {
  analogWrite(LIDAR_PWM_PIN, 0);
  lidarRunning = false;
  lidarPwm = 0;
  lidarFault = reason;
}

void startLidar() {
  memset(lidarDistanceMm, 0, sizeof(lidarDistanceMm));
  lidarPacketPos = 0;
  while (Serial.available()) Serial.read();
  lidarGoodPackets = 0;
  lidarBadPackets = 0;
  lidarRpm = 0;
  lidarLastGoodMs = millis();
  lidarFault = "none";
  lidarPwm = 200;
  lidarRunning = true;
  analogWrite(LIDAR_PWM_PIN, lidarPwm);
}

void acceptLidarPacket(const uint8_t* packet) {
  if (!lidarChecksumOK(packet)) {
    ++lidarBadPackets;
    return;
  }

  ++lidarGoodPackets;
  lidarLastGoodMs = millis();
  const int baseAngle = (packet[1] - 0xA0) * 4;
  const uint16_t speedRaw = packet[2] | (uint16_t(packet[3]) << 8);
  lidarRpm = speedRaw / 64.0f;
  for (int sample = 0; sample < 4; ++sample) {
    const uint8_t* data = &packet[4 + 4 * sample];
    lidarDistanceMm[baseAngle + sample] = (data[1] & 0x80)
      ? 0 : uint16_t(data[0] | ((data[1] & 0x3F) << 8));
  }

  // Packet 0xF9 covers the last four degrees. Adjust motor duty once/turn.
  if (packet[1] == 0xF9) {
    if (lidarRpm < LIDAR_TARGET_RPM - 10) ++lidarPwm;
    else if (lidarRpm > LIDAR_TARGET_RPM + 10) --lidarPwm;
    lidarPwm = constrain(lidarPwm, 80, 255);
    analogWrite(LIDAR_PWM_PIN, lidarPwm);
  }
}

void pollLidar() {
  // Drain even when stopped, so stale bytes cannot look like a fresh scan.
  while (Serial.available()) {
    const uint8_t value = Serial.read();
    if (!lidarRunning) continue;
    if (lidarPacketPos == 0 && value != 0xFA) continue;
    if (lidarPacketPos == 1 && (value < 0xA0 || value > 0xF9)) {
      lidarPacketPos = 0;
      continue;
    }
    lidarPacket[lidarPacketPos++] = value;
    if (lidarPacketPos == sizeof(lidarPacket)) {
      acceptLidarPacket(lidarPacket);
      lidarPacketPos = 0;
    }
  }
  if (lidarRunning && millis() - lidarLastGoodMs > LIDAR_PACKET_TIMEOUT_MS) {
    stopLidar("no valid packets for 5 seconds");
  }
}

void startMotion(MotionState requested, int speedValue, unsigned long durationMs) {
  speedValue = constrain(speedValue, 0, 255);
  if (speedValue == 0 || requested == MOTION_STOPPED) {
    stopAll();
    return;
  }

  switch (requested) {
    case MOTION_FORWARD:  motorA(true, speedValue);  motorB(true, speedValue);  break;
    case MOTION_BACKWARD: motorA(false, speedValue); motorB(false, speedValue); break;
    case MOTION_LEFT:     motorA(false, speedValue); motorB(true, speedValue);  break;
    case MOTION_RIGHT:    motorA(true, speedValue);  motorB(false, speedValue); break;
    default: stopAll(); return;
  }

  motionState = requested;
  motionDeadline = millis() + durationMs;
  motionLeaseActive = true;
}

void startTankDrive(int leftSpeed, int rightSpeed, unsigned long durationMs) {
  leftSpeed = constrain(leftSpeed, -255, 255);
  rightSpeed = constrain(rightSpeed, -255, 255);
  if (leftSpeed == 0 && rightSpeed == 0) {
    stopAll();
    return;
  }

  motorA(leftSpeed >= 0, abs(leftSpeed));
  motorB(rightSpeed >= 0, abs(rightSpeed));

  if (leftSpeed >= 0 && rightSpeed >= 0) motionState = MOTION_FORWARD;
  else if (leftSpeed <= 0 && rightSpeed <= 0) motionState = MOTION_BACKWARD;
  else if (leftSpeed < rightSpeed) motionState = MOTION_LEFT;
  else motionState = MOTION_RIGHT;

  motionDeadline = millis() + durationMs;
  motionLeaseActive = true;
}

const char* modeName() {
  switch (controlMode) {
    case MODE_HUMAN: return "human";
    case MODE_CONTROLLER: return "controller";
    default: return "ai";
  }
}

const char* motionName() {
  switch (motionState) {
    case MOTION_FORWARD: return "forward";
    case MOTION_BACKWARD: return "backward";
    case MOTION_LEFT: return "left";
    case MOTION_RIGHT: return "right";
    default: return "stopped";
  }
}

const char htmlPage[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pitdivers Rover</title>
  <style>
    body { font-family:sans-serif; text-align:center; background:#111; color:#eee; }
    .row { margin:12px 0; }
    button { width:90px; height:90px; margin:6px; font-size:18px;
      border-radius:12px; border:none; background:#2a7; color:white; }
    button:active { background:#175; }
    button:disabled { background:#555; color:#999; }
    #stopBtn { background:#c33; }
    #status { display:flex; align-items:center; justify-content:center; gap:8px; }
    #statusDot { width:12px; height:12px; border-radius:50%; background:#777; }
    #speedRow { margin:20px auto; width:80%; max-width:300px; }
    input[type=range] { width:100%; }
    .drive { touch-action:none; user-select:none; }
    .modeBtn { width:110px; height:48px; }
    #modeText { font-weight:bold; text-transform:uppercase; }
  </style>
</head>
<body>
  <h2>Pitdivers Rover</h2>
  <div id="status"><div id="statusDot"></div><span id="statusText">Checking...</span></div>
  <div class="row">
    Mode: <span id="modeText">Human</span><br>
    <button class="modeBtn" onclick="setMode('human')">Human</button>
    <button class="modeBtn" onclick="setMode('controller')">Controller</button>
    <button class="modeBtn" onclick="setMode('ai')">AI</button>
  </div>
  <div class="row" id="controllerHelp" hidden>
    Run the PC controller bridge. Left stick: drive and steer; B: emergency stop.
  </div>
  <div class="row"><button class="drive" data-direction="forward">Forward</button></div>
  <div class="row">
    <button class="drive" data-direction="left">Left</button>
    <button id="stopBtn" onclick="stopMove()">Stop</button>
    <button class="drive" data-direction="right">Right</button>
  </div>
  <div class="row"><button class="drive" data-direction="backward">Backward</button></div>
  <div id="speedRow">
    <label>Speed: <span id="speedVal">140</span></label><br>
    <input type="range" id="speed" min="60" max="255" value="140">
  </div>
  <div class="row">
    <h3>LiDAR bench test</h3>
    <button onclick="fetch('/api/lidar/start',{method:'POST'})">LiDAR Start</button>
    <button onclick="fetch('/api/lidar/stop',{method:'POST'})">LiDAR Stop</button>
    <p id="lidarStatus">LiDAR stopped</p>
    <small>Keep the rover lifted so its wheels can spin safely during testing.</small>
  </div>
  <script>
    let currentMode = 'human';
    let holdTimer = null;
    const speedSlider = document.getElementById('speed');

    function setStatus(ok) {
      document.getElementById('statusDot').style.background = ok ? '#2ecc71' : '#e74c3c';
      document.getElementById('statusText').innerText = ok ? 'Connected' : 'Disconnected';
    }
    function sendMove(direction) {
      fetch('/' + direction).catch(() => stopMove());
    }
    function startMove(direction) {
      if (currentMode !== 'human') return;
      stopMove(false);
      sendMove(direction);
      holdTimer = setInterval(() => sendMove(direction), 250);
    }
    function stopMove(sendStop = true) {
      if (holdTimer) clearInterval(holdTimer);
      holdTimer = null;
      if (sendStop) fetch('/stop').catch(() => {});
    }

    document.querySelectorAll('.drive').forEach(button => {
      button.addEventListener('pointerdown', event => {
        event.preventDefault();
        button.setPointerCapture(event.pointerId);
        startMove(button.dataset.direction);
      });
      button.addEventListener('pointerup', () => stopMove());
      button.addEventListener('pointercancel', () => stopMove());
      button.addEventListener('lostpointercapture', () => stopMove());
      button.addEventListener('contextmenu', event => event.preventDefault());
    });
    window.addEventListener('blur', () => stopMove());
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) stopMove();
    });

    speedSlider.oninput = function() {
      document.getElementById('speedVal').innerText = this.value;
      fetch('/speed?value=' + this.value).catch(() => {});
    };
    function updateFromStatus(status) {
      currentMode = status.mode;
      document.getElementById('modeText').innerText = status.mode;
      document.querySelectorAll('.drive').forEach(button => {
        button.disabled = status.mode !== 'human';
      });
      speedSlider.disabled = status.mode !== 'human';
      document.getElementById('controllerHelp').hidden = status.mode !== 'controller';
      setStatus(true);
    }
    function setMode(mode) {
      stopMove();
      fetch('/mode?value=' + mode, { method:'POST' })
        .then(response => {
          if (!response.ok) throw new Error('Mode change failed');
          return response.json();
        })
        .then(updateFromStatus)
        .catch(() => setStatus(false));
    }
    function checkConnection() {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 1000);
      fetch('/api/status', { signal:controller.signal })
        .then(response => response.json())
        .then(status => { clearTimeout(timeoutId); updateFromStatus(status); })
        .catch(() => setStatus(false));
    }
    setInterval(checkConnection, 1500);
    checkConnection();
    async function updateLidar() {
      try {
        const r = await fetch('/api/lidar/status');
        const s = await r.json();
        document.getElementById('lidarStatus').textContent = s.running
          ? `LiDAR ${s.rpm} RPM, PWM ${s.pwm}, valid packets ${s.good}, bad ${s.bad}, points ${s.points}`
          : `LiDAR stopped: ${s.fault}`;
      } catch (_) {
        document.getElementById('lidarStatus').textContent = 'LiDAR status unavailable';
      }
    }
    setInterval(updateLidar, 1000);
    updateLidar();
  </script>
</body>
</html>
)rawliteral";

void handleRoot() { server.send(200, "text/html", htmlPage); }

bool requireHumanMode() {
  if (controlMode == MODE_HUMAN) return true;
  server.send(409, "application/json", "{\"ok\":false,\"error\":\"AI mode is active\"}");
  return false;
}

void handleForward() {
  if (!requireHumanMode()) return;
  startMotion(MOTION_FORWARD, currentSpeed, HUMAN_LEASE_MS);
  server.send(200, "text/plain", "forward");
}
void handleBackward() {
  if (!requireHumanMode()) return;
  startMotion(MOTION_BACKWARD, currentSpeed, HUMAN_LEASE_MS);
  server.send(200, "text/plain", "backward");
}
void handleLeft() {
  if (!requireHumanMode()) return;
  startMotion(MOTION_LEFT, currentSpeed, HUMAN_LEASE_MS);
  server.send(200, "text/plain", "left");
}
void handleRight() {
  if (!requireHumanMode()) return;
  startMotion(MOTION_RIGHT, currentSpeed, HUMAN_LEASE_MS);
  server.send(200, "text/plain", "right");
}

// Stop is intentionally always available, regardless of mode.
void handleStop() {
  stopAll();
  server.send(200, "text/plain", "stop");
}

void handleSpeed() {
  if (!requireHumanMode()) return;
  if (server.hasArg("value")) {
    currentSpeed = constrain(server.arg("value").toInt(), 60, 255);
  }
  server.send(200, "text/plain", String(currentSpeed));
}

void handleMode() {
  if (!server.hasArg("value")) {
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"Missing mode\"}");
    return;
  }
  String requestedMode = server.arg("value");
  if (requestedMode != "human" && requestedMode != "controller" && requestedMode != "ai") {
    server.send(400, "application/json",
                "{\"ok\":false,\"error\":\"Mode must be human, controller, or ai\"}");
    return;
  }
  stopAll();
  if (requestedMode == "human") controlMode = MODE_HUMAN;
  else if (requestedMode == "controller") controlMode = MODE_CONTROLLER;
  else controlMode = MODE_AI;
  server.send(200, "application/json",
              String("{\"ok\":true,\"mode\":\"") + modeName() + "\"}");
}

bool requireAiAccess() {
  if (controlMode != MODE_AI) {
    server.send(409, "application/json", "{\"ok\":false,\"error\":\"AI mode is not active\"}");
    return false;
  }
  if (server.header("X-API-Key") != controlApiKey) {
    server.send(401, "application/json", "{\"ok\":false,\"error\":\"Invalid API key\"}");
    return false;
  }
  return true;
}

bool requireControllerAccess() {
  if (controlMode != MODE_CONTROLLER) {
    server.send(409, "application/json",
                "{\"ok\":false,\"error\":\"Controller mode is not active\"}");
    return false;
  }
  if (server.header("X-API-Key") != controlApiKey) {
    server.send(401, "application/json", "{\"ok\":false,\"error\":\"Invalid API key\"}");
    return false;
  }
  return true;
}

bool parseMotion(const String& direction, MotionState& parsed) {
  if (direction == "forward") parsed = MOTION_FORWARD;
  else if (direction == "backward") parsed = MOTION_BACKWARD;
  else if (direction == "left") parsed = MOTION_LEFT;
  else if (direction == "right") parsed = MOTION_RIGHT;
  else return false;
  return true;
}

void handleAiMove() {
  if (!requireAiAccess()) return;
  if (!server.hasArg("direction") || !server.hasArg("speed") ||
      !server.hasArg("duration_ms")) {
    server.send(400, "application/json",
                "{\"ok\":false,\"error\":\"Required: direction, speed, duration_ms\"}");
    return;
  }
  MotionState requested;
  if (!parseMotion(server.arg("direction"), requested)) {
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"Invalid direction\"}");
    return;
  }

  int speedValue = constrain(server.arg("speed").toInt(), 0, 255);
  unsigned long durationMs = constrain(
    server.arg("duration_ms").toInt(), 50, (int)MAX_AI_DURATION_MS
  );
  startMotion(requested, speedValue, durationMs);
  server.send(200, "application/json",
              String("{\"ok\":true,\"motion\":\"") + motionName() +
              "\",\"duration_ms\":" + durationMs + "}");
}

void handleAiStop() {
  if (!requireAiAccess()) return;
  stopAll();
  server.send(200, "application/json", "{\"ok\":true,\"motion\":\"stopped\"}");
}

void handleControllerDrive() {
  if (!requireControllerAccess()) return;
  if (!server.hasArg("left") || !server.hasArg("right")) {
    server.send(400, "application/json",
                "{\"ok\":false,\"error\":\"Required: left and right\"}");
    return;
  }

  int leftSpeed = constrain(server.arg("left").toInt(), -255, 255);
  int rightSpeed = constrain(server.arg("right").toInt(), -255, 255);
  startTankDrive(leftSpeed, rightSpeed, CONTROLLER_LEASE_MS);
  server.send(200, "application/json",
              String("{\"ok\":true,\"left\":") + leftSpeed +
              ",\"right\":" + rightSpeed + "}");
}

void handleStatus() {
  String json = String("{\"ok\":true,\"mode\":\"") + modeName() +
                "\",\"motion\":\"" + motionName() +
                "\",\"speed\":" + currentSpeed +
                ",\"max_ai_duration_ms\":" + MAX_AI_DURATION_MS + "}";
  server.send(200, "application/json", json);
}

void handleLidarStatus() {
  int points = 0;
  for (int i = 0; i < 360; ++i) if (lidarDistanceMm[i] != 0) ++points;
  String json = String("{\"running\":") + (lidarRunning ? "true" : "false") +
    ",\"rpm\":" + String(lidarRpm, 0) +
    ",\"pwm\":" + lidarPwm +
    ",\"good\":" + lidarGoodPackets +
    ",\"bad\":" + lidarBadPackets +
    ",\"points\":" + points +
    ",\"fault\":\"" + lidarFault + "\"}";
  server.send(200, "application/json", json);
}

void handleLidarScan() {
  String json;
  json.reserve(2200);
  json = "[";
  for (int i = 0; i < 360; ++i) {
    if (i) json += ',';
    json += lidarDistanceMm[i];
  }
  json += ']';
  server.send(200, "application/json", json);
}

void setup() {
  Serial.setRxBufferSize(2048);
  Serial.begin(115200);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);
  pinMode(LIDAR_PWM_PIN, OUTPUT);
  analogWriteRange(255);
  stopAll();
  stopLidar("stopped");

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  unsigned long wifiStart = millis();
  const unsigned long wifiTimeoutMs = 15000;
  while (WiFi.status() != WL_CONNECTED && millis() - wifiStart < wifiTimeoutMs) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Connected. Rover control page: http://");
    Serial.println(WiFi.localIP());
  } else {
    usingFallbackAP = true;
    Serial.println("Could not join WiFi - starting rover hotspot.");
    WiFi.mode(WIFI_AP);
    WiFi.softAP("PitdiversRover", "rover1234");
    Serial.print("Connect to PitdiversRover, then open http://");
    Serial.println(WiFi.softAPIP());
  }

  server.on("/", HTTP_GET, handleRoot);
  server.on("/forward", HTTP_GET, handleForward);
  server.on("/backward", HTTP_GET, handleBackward);
  server.on("/left", HTTP_GET, handleLeft);
  server.on("/right", HTTP_GET, handleRight);
  server.on("/stop", HTTP_GET, handleStop);
  server.on("/speed", HTTP_GET, handleSpeed);
  server.on("/mode", HTTP_POST, handleMode);
  server.on("/api/move", HTTP_POST, handleAiMove);
  server.on("/api/stop", HTTP_POST, handleAiStop);
  server.on("/api/controller", HTTP_POST, handleControllerDrive);
  server.on("/api/status", HTTP_GET, handleStatus);
  server.on("/api/lidar/start", HTTP_POST, []() {
    startLidar();
    server.send(200, "application/json", "{\"ok\":true,\"running\":true}");
  });
  server.on("/api/lidar/stop", HTTP_POST, []() {
    stopLidar("stopped by user");
    server.send(200, "application/json", "{\"ok\":true,\"running\":false}");
  });
  server.on("/api/lidar/status", HTTP_GET, handleLidarStatus);
  server.on("/api/lidar/scan", HTTP_GET, handleLidarScan);
  server.collectHeaders("X-API-Key");
  server.begin();
  // UART0 RX moves from USB RX/GPIO3 to D7/GPIO13. USB upload still works
  // because this remapping happens only after the firmware starts.
  Serial.flush();
  Serial.swap();
}

void loop() {
  server.handleClient();
  pollLidar();

  // Signed subtraction is safe when millis() wraps around.
  if (motionLeaseActive && (long)(millis() - motionDeadline) >= 0) {
    stopAll();
  }

  if (!usingFallbackAP && WiFi.status() != WL_CONNECTED &&
      millis() - lastReconnectCheck > 5000) {
    lastReconnectCheck = millis();
    stopAll();
    WiFi.reconnect();
  }
}
