#include <Arduino.h>
#include <WebServer.h>
#include <WiFi.h>

#include "secrets.h"

// Freenove ESP32-S3 -> existing L298N input wires.
constexpr uint8_t IN1 = 1;   // yellow
constexpr uint8_t IN2 = 2;   // green
constexpr uint8_t IN3 = 41;  // blue
constexpr uint8_t IN4 = 42;  // purple

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
setInterval(()=>fetch('/api/status').then(r=>r.json()).then(s=>{document.querySelector('#status').textContent='Connected: '+s.motion}).catch(()=>{document.querySelector('#status').textContent='Disconnected'}),1000);
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
  server.begin();
  Serial.println("Wheel pins: IN1=GPIO1, IN2=GPIO2, IN3=GPIO41, IN4=GPIO42");
}

void loop() {
  server.handleClient();
  if (moving && millis() - lastDriveMs > DRIVE_LEASE_MS) stopMotors();
  if (WiFi.getMode() == WIFI_STA && WiFi.status() != WL_CONNECTED) stopMotors();
  delay(2);
}
