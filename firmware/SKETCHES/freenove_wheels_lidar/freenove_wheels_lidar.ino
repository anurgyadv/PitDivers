#include <Arduino.h>
#include <WebServer.h>
#include <WiFi.h>
#include <string.h>

#include "secrets.h"

// Freenove ESP32-S3 -> existing L298N input wires.
constexpr uint8_t IN1 = 1;   // yellow
constexpr uint8_t IN2 = 2;   // green
constexpr uint8_t IN3 = 41;  // blue
constexpr uint8_t IN4 = 42;  // purple
constexpr uint8_t LIDAR_RX = 14;   // LDS02RR pad 2 TX -> ESP32-S3 RX
constexpr uint8_t LIDAR_PWM = 47; // MOSFET driver gate/control input
constexpr uint32_t LIDAR_TIMEOUT_MS = 5000;
constexpr int TARGET_RPM = 300;
HardwareSerial lidarSerial(1);
uint8_t packet[22] = {};
uint8_t packetPos = 0;
uint16_t distanceMm[360] = {};
bool lidarRunning = false;
uint8_t lidarDuty = 0;
float lidarRpm = 0;
uint32_t goodPackets = 0;
uint32_t badPackets = 0;
uint32_t lastGoodPacketMs = 0;
const char* lidarFault = "stopped";

constexpr uint32_t DRIVE_LEASE_MS = 600;
constexpr uint8_t START_SPEED = 160;
WebServer server(80);
uint8_t speedValue = START_SPEED;
uint32_t lastDriveMs = 0;
bool moving = false;
const char* motion = "stopped";

void stopMotors() {
  analogWrite(IN1, 0);
  analogWrite(IN2, 0);
  analogWrite(IN3, 0);
  analogWrite(IN4, 0);
  moving = false;
  motion = "stopped";
}

void driveMotor(uint8_t forwardPin, uint8_t reversePin, int value) {
  value = constrain(value, -255, 255);
  // Switch both inputs off before changing direction.
  analogWrite(forwardPin, 0);
  analogWrite(reversePin, 0);
  if (value > 0) analogWrite(forwardPin, value);
  if (value < 0) analogWrite(reversePin, -value);
}

void drive(int left, int right, const char* name) {
  driveMotor(IN1, IN2, left);
  driveMotor(IN3, IN4, right);
  moving = left != 0 || right != 0;
  motion = moving ? name : "stopped";
  lastDriveMs = millis();
}

bool checksumOK(const uint8_t* data) {
  uint32_t sum = 0;
  for (int i = 0; i < 10; ++i) {
    sum = (sum << 1) + uint16_t(data[2 * i] | (uint16_t(data[2 * i + 1]) << 8));
  }
  sum = ((sum & 0x7FFF) + (sum >> 15)) & 0x7FFF;
  return sum == uint16_t(data[20] | (uint16_t(data[21]) << 8));
}

void stopLidar(const char* reason) {
  analogWrite(LIDAR_PWM, 0);
  lidarRunning = false;
  lidarDuty = 0;
  lidarFault = reason;
}

void startLidar() {
  memset(distanceMm, 0, sizeof(distanceMm));
  while (lidarSerial.available()) lidarSerial.read();
  packetPos = 0;
  goodPackets = badPackets = 0;
  lidarRpm = 0;
  lastGoodPacketMs = millis();
  lidarFault = "none";
  lidarDuty = 200;
  lidarRunning = true;
  analogWrite(LIDAR_PWM, lidarDuty);
}

void acceptPacket(const uint8_t* data) {
  if (!checksumOK(data)) { ++badPackets; return; }
  ++goodPackets;
  lastGoodPacketMs = millis();
  const int angle = (data[1] - 0xA0) * 4;
  lidarRpm = uint16_t(data[2] | (uint16_t(data[3]) << 8)) / 64.0f;
  for (int i = 0; i < 4; ++i) {
    const uint8_t* sample = data + 4 + i * 4;
    distanceMm[angle + i] = sample[1] & 0x80 ? 0 :
      uint16_t(sample[0] | ((sample[1] & 0x3F) << 8));
  }
  if (data[1] == 0xF9) {
    if (lidarRpm < TARGET_RPM - 10 && lidarDuty < 255) ++lidarDuty;
    else if (lidarRpm > TARGET_RPM + 10 && lidarDuty > 80) --lidarDuty;
    analogWrite(LIDAR_PWM, lidarDuty);
  }
}

void pollLidar() {
  while (lidarSerial.available()) {
    const uint8_t value = lidarSerial.read();
    if (!lidarRunning) continue;
    if (packetPos == 0 && value != 0xFA) continue;
    if (packetPos == 1 && (value < 0xA0 || value > 0xF9)) {
      packetPos = 0;
      continue;
    }
    packet[packetPos++] = value;
    if (packetPos == sizeof(packet)) {
      acceptPacket(packet);
      packetPos = 0;
    }
  }
  if (lidarRunning && millis() - lastGoodPacketMs > LIDAR_TIMEOUT_MS)
    stopLidar("no valid packets for 5 seconds");
}

const char PAGE[] PROGMEM = R"HTML(
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PitDivers wheel test</title><style>
body{background:#111;color:white;font:18px sans-serif;text-align:center;max-width:460px;margin:20px auto}
button{width:110px;height:78px;margin:6px;border:0;border-radius:12px;background:#287;color:white;font-size:19px;touch-action:none}
#stop{background:#c33}input{width:85%}.status{min-height:24px}
</style></head><body><h2>PitDivers wheel test</h2>
<p>Lift the wheels off the ground before the first test.</p>
<p class="status" id="status">Connecting...</p>
<div><button data-drive="forward">Forward</button></div>
<div><button data-drive="left">Left</button><button id="stop">STOP</button><button data-drive="right">Right</button></div>
<div><button data-drive="backward">Reverse</button></div>
<p>Speed <span id="speedText">160</span>/255</p><input id="speed" type="range" min="80" max="255" value="160">
<h3>LiDAR scan test</h3><button id="lidarStart">Start LiDAR</button><button id="lidarStop">Stop LiDAR</button>
<p id="lidarStatus">LiDAR stopped</p><p>Scan data: <a href="/api/lidar/scan" style="color:#8df">/api/lidar/scan</a></p>
<script>
let timer;
function stop(){clearInterval(timer);timer=undefined;fetch('/stop').catch(()=>{});}
function send(name){fetch('/'+name).catch(stop);}
document.querySelectorAll('[data-drive]').forEach(b=>{
 b.onpointerdown=e=>{e.preventDefault();b.setPointerCapture(e.pointerId);stop();send(b.dataset.drive);timer=setInterval(()=>send(b.dataset.drive),200)};
 b.onpointerup=stop;b.onpointercancel=stop;b.onlostpointercapture=stop;
});
document.querySelector('#stop').onclick=stop;
document.querySelector('#speed').oninput=e=>{let v=e.target.value;document.querySelector('#speedText').textContent=v;fetch('/speed?value='+v).catch(()=>{})};
window.onblur=stop;document.onvisibilitychange=()=>{if(document.hidden)stop()};
document.querySelector('#lidarStart').onclick=()=>fetch('/api/lidar/start',{method:'POST'});
document.querySelector('#lidarStop').onclick=()=>fetch('/api/lidar/stop',{method:'POST'});
setInterval(()=>fetch('/api/status').then(r=>r.json()).then(s=>{document.querySelector('#status').textContent='Connected: '+s.motion}).catch(()=>{document.querySelector('#status').textContent='Disconnected'}),1000);
setInterval(()=>fetch('/api/lidar/status').then(r=>r.json()).then(s=>{document.querySelector('#lidarStatus').textContent=s.running?`LiDAR ${s.rpm} RPM, PWM ${s.pwm}, good ${s.good}, bad ${s.bad}, points ${s.points}`:`LiDAR stopped: ${s.fault}`}).catch(()=>{}),1000);
</script></body></html>
)HTML";

void respondDrive(int left, int right, const char* name) {
  drive(left, right, name);
  server.send(200, "text/plain", name);
}

void setup() {
  Serial.begin(115200);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);
  stopMotors();
  pinMode(LIDAR_PWM, OUTPUT);
  stopLidar("stopped");
  lidarSerial.setRxBufferSize(2048);
  lidarSerial.begin(115200, SERIAL_8N1, LIDAR_RX, -1);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Joining home Wi-Fi");
  const uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    delay(250);
    Serial.print('.');
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Open http://"); Serial.println(WiFi.localIP());
  } else {
    WiFi.mode(WIFI_AP);
    WiFi.softAP("PitDivers-Wheels", "rover1234");
    Serial.print("Connect to PitDivers-Wheels, then open http://");
    Serial.println(WiFi.softAPIP());
  }

  server.on("/", HTTP_GET, [] { server.send_P(200, "text/html", PAGE); });
  server.on("/forward", HTTP_GET, [] { respondDrive(speedValue, speedValue, "forward"); });
  server.on("/backward", HTTP_GET, [] { respondDrive(-speedValue, -speedValue, "backward"); });
  server.on("/left", HTTP_GET, [] { respondDrive(-speedValue, speedValue, "left"); });
  server.on("/right", HTTP_GET, [] { respondDrive(speedValue, -speedValue, "right"); });
  server.on("/stop", HTTP_GET, [] { stopMotors(); server.send(200, "text/plain", "stopped"); });
  server.on("/speed", HTTP_GET, [] {
    if (server.hasArg("value")) speedValue = constrain(server.arg("value").toInt(), 80, 255);
    server.send(200, "text/plain", String(speedValue));
  });
  server.on("/api/status", HTTP_GET, [] {
    server.send(200, "application/json", String("{\"motion\":\"") + motion + "\",\"speed\":" + speedValue + "}");
  });
  server.on("/api/lidar/start", HTTP_POST, [] {
    startLidar();
    server.send(200, "application/json", "{\"running\":true}");
  });
  server.on("/api/lidar/stop", HTTP_POST, [] {
    stopLidar("stopped by user");
    server.send(200, "application/json", "{\"running\":false}");
  });
  server.on("/api/lidar/status", HTTP_GET, [] {
    int points = 0;
    for (const uint16_t value : distanceMm) if (value != 0) ++points;
    String json = String("{\"running\":") + (lidarRunning ? "true" : "false") +
      ",\"rpm\":" + String(lidarRpm, 0) + ",\"pwm\":" + lidarDuty +
      ",\"good\":" + goodPackets + ",\"bad\":" + badPackets +
      ",\"points\":" + points + ",\"fault\":\"" + lidarFault + "\"}";
    server.send(200, "application/json", json);
  });
  server.on("/api/lidar/scan", HTTP_GET, [] {
    String json;
    json.reserve(2200);
    json = "[";
    for (int i = 0; i < 360; ++i) {
      if (i) json += ',';
      json += distanceMm[i];
    }
    json += ']';
    server.send(200, "application/json", json);
  });
  server.begin();
  Serial.println("Wheel pins: IN1=GPIO1, IN2=GPIO2, IN3=GPIO41, IN4=GPIO42");
  Serial.println("LiDAR: TX->GPIO14, driver gate->GPIO47, shared GND, regulated 5V");
}

void loop() {
  server.handleClient();
  pollLidar();
  if (moving && millis() - lastDriveMs > DRIVE_LEASE_MS) stopMotors();
  if (WiFi.getMode() == WIFI_STA && WiFi.status() != WL_CONNECTED) stopMotors();
  delay(2);
}
