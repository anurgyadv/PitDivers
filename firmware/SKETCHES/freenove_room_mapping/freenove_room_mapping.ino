#include <Arduino.h>
#include <DHTesp.h>
#include <SD_MMC.h>
#include <WebServer.h>
#include <WiFi.h>
#include <Wire.h>
#include <math.h>
#include <string.h>
#include <stdlib.h>

#include "secrets.h"
#include "TurnCalibration.h"
#include "OnboardMotion.h"
#include "ControlTypes.h"
void controlTask(void*);
void setupControlRoutes();
#include <Preferences.h>
TurnCalibration turnCalibration;
Preferences turnPreferences;
bool calibrationSaved=false;
OnboardMotion onboard;
QueueHandle_t controlQueue, scanQueue;
SemaphoreHandle_t storageMutex;
struct StorageLock {
  bool held;
  explicit StorageLock(TickType_t wait):held(xSemaphoreTake(storageMutex,wait)==pdTRUE) {}
  ~StorageLock(){if(held)xSemaphoreGive(storageMutex);}
};
uint32_t logBytes=0;
portMUX_TYPE sharedMux=portMUX_INITIALIZER_UNLOCKED;
ControlView sharedView;
ScanRecord sharedScan;
uint32_t droppedScans=0,calibrationVersion=0;
int rawFrontIndex=192; // clockwise raw indices: -degrees(2.936) mod 360
bool emergencyStop=false;
ControlView controlView() { portENTER_CRITICAL(&sharedMux); auto v=sharedView; portEXIT_CRITICAL(&sharedMux); return v; }
ScanRecord scanView() { portENTER_CRITICAL(&sharedMux); auto v=sharedScan; portEXIT_CRITICAL(&sharedMux); return v; }
void submit(ControlRequest request) {
  if (request.kind==StopControl) xQueueReset(controlQueue);
  if (xQueueSend(controlQueue,&request,0)!=pdTRUE) {
    portENTER_CRITICAL(&sharedMux);emergencyStop=true;portEXIT_CRITICAL(&sharedMux);
  }
}

// Freenove ESP32-S3 -> existing L298N input wires.
constexpr uint8_t IN1 = 1;   // yellow
constexpr uint8_t IN2 = 2;   // green
constexpr uint8_t IN3 = 41;  // blue
constexpr uint8_t IN4 = 42;  // purple
constexpr uint8_t LIDAR_RX = 14;   // LDS02RR pad 2 TX -> ESP32-S3 RX
constexpr uint8_t LIDAR_PWM = 47; // MOSFET driver gate/control input
constexpr uint8_t DHT_PIN = 21;
constexpr uint8_t IMU_SDA = 3;
constexpr uint8_t IMU_SCL = 48; // move the wire from GPIO46 to GPIO48
constexpr uint8_t IMU_ADDRESS = 0x68;
constexpr uint8_t SD_CMD = 38;
constexpr uint8_t SD_CLK = 39;
constexpr uint8_t SD_D0 = 40;
constexpr char LOG_PATH[] = "/pitdivers_scans.jsonl";
bool storageReady = false;
uint32_t storageErrors = 0;
uint32_t bootId = 0;
constexpr uint32_t DHT_INTERVAL_MS = 2000;
constexpr uint32_t IMU_INTERVAL_MS = 10;
DHTesp dht;
bool dhtValid = false;
float temperatureC = 0;
float humidityPercent = 0;
uint32_t lastDhtMs = 0;
uint32_t lastDhtOkMs = 0;
bool imuValid = false;
float accelG[3] = {};
float gyroDps[3] = {};
float imuTemperatureC = 0;
uint32_t lastImuOkMs = 0;
constexpr uint32_t LIDAR_TIMEOUT_MS = 5000;
constexpr int TARGET_RPM = 300;
HardwareSerial lidarSerial(1);
uint8_t packet[22] = {};
uint8_t packetPos = 0;
uint16_t distanceMm[360] = {};
uint16_t cycleDistanceMm[360] = {};
uint16_t fullDistanceMm[360] = {};
uint8_t nextCycleIndex = 0xA0;
uint32_t cycleStartMs = 0;
uint32_t fullScanStartMs = 0;
uint32_t fullScanEndMs = 0;
uint32_t fullScanSeq = 0;
bool fullScanReady = false;
bool lidarRunning = false;
uint8_t lidarDuty = 0;
float lidarRpm = 0;
uint32_t goodPackets = 0;
uint32_t badPackets = 0;
uint32_t lidarBytes = 0;
uint32_t lidarHeaders = 0;
uint32_t lidarIndexErrors = 0;
uint32_t lastGoodPacketMs = 0;
const char* lidarFault = "stopped";

void publishFullScan();

constexpr uint8_t START_SPEED = 160;
WebServer server(80);
uint8_t speedValue = START_SPEED;
uint32_t lastWifiReconnectMs = 0;

void stopMotors() { submit({StopControl}); }

void driveMotor(uint8_t forwardPin, uint8_t reversePin, int value) {
  value = constrain(value, -255, 255);
  // Switch both inputs off before changing direction.
  analogWrite(forwardPin, 0);
  analogWrite(reversePin, 0);
  if (value > 0) analogWrite(forwardPin, value);
  if (value < 0) analogWrite(reversePin, -value);
}

void drive(int left,int right,const char*) { submit({ManualControl,0,0,left,right}); }

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
  nextCycleIndex = 0xA0;
  fullScanReady = false;
  portENTER_CRITICAL(&sharedMux);sharedScan=ScanRecord{};portEXIT_CRITICAL(&sharedMux);
  goodPackets = badPackets = 0;
  lidarBytes = lidarHeaders = lidarIndexErrors = 0;
  lidarRpm = 0;
  lastGoodPacketMs = millis();
  lidarFault = "none";
  lidarDuty = 200;
  lidarRunning = true;
  analogWrite(LIDAR_PWM, lidarDuty);
}

void acceptPacket(const uint8_t* data) {
  if (!checksumOK(data)) {
    ++badPackets;
    nextCycleIndex = 0xA0;
    return;
  }
  ++goodPackets;
  lastGoodPacketMs = millis();
  const int angle = (data[1] - 0xA0) * 4;
  lidarRpm = uint16_t(data[2] | (uint16_t(data[3]) << 8)) / 64.0f;
  for (int i = 0; i < 4; ++i) {
    const uint8_t* sample = data + 4 + i * 4;
    distanceMm[angle + i] = sample[1] & 0x80 ? 0 :
      uint16_t(sample[0] | ((sample[1] & 0x3F) << 8));
  }
  // A complete scan requires all 90 checksum-valid packets in order.
  const uint8_t index = data[1];
  if (index == 0xA0) {
    nextCycleIndex = 0xA0;
    cycleStartMs = millis();
  }
  if (index == nextCycleIndex) {
    for (int i = 0; i < 4; ++i) cycleDistanceMm[angle + i] = distanceMm[angle + i];
    if (index == 0xF9) {
      memcpy(fullDistanceMm, cycleDistanceMm, sizeof(fullDistanceMm));
      fullScanStartMs = cycleStartMs;
      fullScanEndMs = millis();
      ++fullScanSeq;
      fullScanReady = true;
      nextCycleIndex = 0xA0;
      publishFullScan();
    } else {
      nextCycleIndex = index + 1;
    }
  } else {
    nextCycleIndex = 0xA0;
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
    ++lidarBytes;
    if (packetPos == 0 && value == 0xFA) ++lidarHeaders;
    if (packetPos == 0 && value != 0xFA) continue;
    if (packetPos == 1 && (value < 0xA0 || value > 0xF9)) {
      ++lidarIndexErrors;
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

bool imuWrite(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(IMU_ADDRESS);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool readImu() {
  Wire.beginTransmission(IMU_ADDRESS);
  Wire.write(0x3B); // ACCEL_XOUT_H, first of 14 measurement bytes
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom(IMU_ADDRESS, uint8_t(14)) != 14)
    return false;
  int16_t raw[7];
  for (int i = 0; i < 7; ++i)
    raw[i] = int16_t((uint16_t(Wire.read()) << 8) | Wire.read());
  for (int i = 0; i < 3; ++i) {
    accelG[i] = raw[i] / 16384.0f;   // default ±2 g range
    gyroDps[i] = raw[i + 4] / 131.0f; // default ±250 degrees/s
  }
  imuTemperatureC = raw[3] / 340.0f + 36.53f;
  return true;
}

void pollSensors() {
  const uint32_t now = millis();
  if (!controlView().calActive && now - lastDhtMs >= DHT_INTERVAL_MS) {
    lastDhtMs = now;
    const TempAndHumidity reading = dht.getTempAndHumidity();
    portENTER_CRITICAL(&sharedMux);
    dhtValid = !isnan(reading.temperature) && !isnan(reading.humidity);
    if (dhtValid) {
      temperatureC = reading.temperature;
      humidityPercent = reading.humidity;
      lastDhtOkMs = now;
    }
    portEXIT_CRITICAL(&sharedMux);
  }

}

String environmentJson() {
  String json = String("{\"ok\":") + (dhtValid ? "true" : "false") +
    ",\"sensor\":\"DHT11\",\"pin\":21";
  if (dhtValid) json += ",\"temperature_c\":" + String(temperatureC, 1) +
                         ",\"humidity_percent\":" + String(humidityPercent, 1);
  return json + "}";
}

String imuJson() {
  auto v=controlView();
  String json=String("{\"ok\":")+(v.imuOK?"true":"false")+",\"sensor\":\"MPU6050\",\"sda\":3,\"scl\":48";
  json+=",\"accel_g\":["+String(v.accel[0],3)+","+String(v.accel[1],3)+","+String(v.accel[2],3)+"]";
  json+=",\"gyro_dps\":["+String(v.gyro[0],3)+","+String(v.gyro[1],3)+","+String(v.gyro[2],3)+"]";
  return json+",\"yaw_deg\":"+String(v.yaw,2)+",\"ready\":"+(v.ready?"true":"false")+"}";
}

void publishFullScan() {
  ScanRecord r;r.seq=fullScanSeq;r.start=fullScanStartMs;r.end=fullScanEndMs;r.rpm=lidarRpm;
  memcpy(r.mm,fullDistanceMm,sizeof(r.mm));memcpy(r.accel,accelG,sizeof(r.accel));memcpy(r.gyro,gyroDps,sizeof(r.gyro));
  r.imuAt=lastImuOkMs;r.imuOK=imuValid;
  portENTER_CRITICAL(&sharedMux);
  r.environmentOK=dhtValid;r.temperature=temperatureC;r.humidity=humidityPercent;r.environmentAt=lastDhtOkMs;
  sharedScan=r;
  portEXIT_CRITICAL(&sharedMux);
  if(xQueueSend(scanQueue,&r,0)!=pdTRUE)++droppedScans;
}

String recordJson(const ScanRecord& r) {
  String json;json.reserve(2900);
  json=String("{\"boot_id\":")+bootId+",\"seq\":"+r.seq+",\"start_ms\":"+r.start+",\"end_ms\":"+r.end+
    ",\"scan_time_ms\":"+(r.end-r.start)+",\"rpm\":"+String(r.rpm,1)+",\"temperature_c\":";
  json+=r.environmentOK?String(r.temperature,1):"null";
  json+=",\"humidity_percent\":";json+=r.environmentOK?String(r.humidity,1):"null";
  json+=",\"environment_age_ms\":";json+=r.environmentOK?String(r.end-r.environmentAt):"null";
  json+=",\"imu\":";
  if(r.imuOK)json+=String("{\"age_ms\":")+(r.end-r.imuAt)+",\"accel_g\":["+String(r.accel[0],3)+","+String(r.accel[1],3)+","+String(r.accel[2],3)+
    "],\"gyro_dps\":["+String(r.gyro[0],3)+","+String(r.gyro[1],3)+","+String(r.gyro[2],3)+"]}";
  else json+="null";
  json+=",\"ranges_mm\":[";
  for(int i=0;i<360;++i){if(i)json+=',';json+=r.mm[i];}
  return json+"]}";
}

void logQueuedScan() {
  StorageLock lock(portMAX_DELAY);
  ScanRecord r;if(xQueueReceive(scanQueue,&r,0)!=pdTRUE)return;
  if(!storageReady)return;
  String json=recordJson(r);
  File log=SD_MMC.open(LOG_PATH,FILE_APPEND);
  if(!log){++storageErrors;storageReady=false;return;}
  const size_t written=log.println(json);log.flush();
  const uint32_t bytes=log.size();log.close();
  portENTER_CRITICAL(&sharedMux);logBytes=bytes;portEXIT_CRITICAL(&sharedMux);
  if(written!=json.length()+2 && written!=json.length()+1){++storageErrors;storageReady=false;}
}

void startStorage() {
  if (!SD_MMC.setPins(SD_CLK, SD_CMD, SD_D0) || !SD_MMC.begin("/sdcard", true)) {
    Serial.println("microSD unavailable: scans will not survive a Wi-Fi outage");
    return;
  }
  storageReady = true;
  // If power failed during a write, separate the partial line from new records.
  File existing = SD_MMC.open(LOG_PATH, FILE_READ);
  if(existing)logBytes=existing.size();
  if (existing && existing.size() > 0) {
    existing.seek(existing.size() - 1);
    const int tail = existing.read();
    existing.close();
    if (tail != '\n') {
      File log = SD_MMC.open(LOG_PATH, FILE_APPEND);
      if (log) { log.println(); log.close(); }
    }
  }
  Serial.println("microSD scan log ready");
}

void storageTask(void*) {
  for(;;) { pollSensors();logQueuedScan();vTaskDelay(pdMS_TO_TICKS(2)); }
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
<p id="storage">Checking microSD storage…</p>
<h3>Sensors</h3><p id="environment">DHT11: waiting…</p><p id="imu">MPU6050: waiting…</p>
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
setInterval(()=>fetch('/api/records/status').then(r=>r.json()).then(s=>{document.querySelector('#storage').textContent=s.storage_ok?`microSD logging: ${s.log_bytes} bytes saved, scan #${s.seq}`:'microSD logging unavailable — disconnected scans cannot be recovered'}).catch(()=>{}),2000);
setInterval(()=>{
 fetch('/api/environment').then(r=>r.json()).then(s=>{document.querySelector('#environment').textContent=s.ok?`DHT11: ${s.temperature_c} °C, ${s.humidity_percent}% RH`:'DHT11: no reading'}).catch(()=>{});
 fetch('/api/imu').then(r=>r.json()).then(s=>{document.querySelector('#imu').textContent=s.ok?`MPU6050: accel ${s.accel_g.join(', ')} g; gyro ${s.gyro_dps.join(', ')} °/s`:'MPU6050: not detected'}).catch(()=>{});
},2000);
</script></body></html>
)HTML";

void respondDrive(int left, int right, const char* name) {
  if (controlView().calActive || controlView().mode==OnboardMotion::Turn || controlView().mode==OnboardMotion::Hold) { server.send(409,"application/json","{\"error\":\"Automatic motion active; press STOP first\"}"); return; }
  drive(left, right, name);
  server.send(200, "text/plain", name);
}

bool parseWheelDuty(const String& raw, int& duty) {
  if (raw.isEmpty()) return false;
  char* end = nullptr;
  const long parsed = strtol(raw.c_str(), &end, 10);
  if (*end != '\0' || parsed < -255 || parsed > 255) return false;
  duty = int(parsed);
  return true;
}

void setup() {
  Serial.begin(115200);
  bootId = esp_random();
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);
  controlQueue=xQueueCreate(8,sizeof(ControlRequest));scanQueue=xQueueCreate(12,sizeof(ScanRecord));
  storageMutex=xSemaphoreCreateMutex();
  if(!controlQueue || !scanQueue || !storageMutex){Serial.println("Control allocation failed");while(true)delay(1000);}
  driveMotor(IN1,IN2,0);driveMotor(IN3,IN4,0);
  turnPreferences.begin("turn-cal", false);
  calibrationSaved=turnPreferences.getBool("valid",false);
  pinMode(LIDAR_PWM, OUTPUT);
  stopLidar("stopped");
  lidarSerial.setRxBufferSize(8192);
  lidarSerial.begin(115200, SERIAL_8N1, LIDAR_RX, -1);
  startStorage();
  dht.setup(DHT_PIN, DHTesp::DHT11);
  Wire.begin(IMU_SDA, IMU_SCL);
  Wire.setClock(100000);
  imuValid = imuWrite(0x6B, 0x00); // wake the MPU6050
  imuValid = imuWrite(0x1B, 0x00) && imuValid; // explicit +/-250 deg/s
  imuValid = imuWrite(0x1A, 0x03) && imuValid; // 42 Hz gyro filter
  Wire.setTimeOut(20);
  lastDhtMs = millis() - DHT_INTERVAL_MS;

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

  onboard.previous=millis();
  if(xTaskCreatePinnedToCore(controlTask,"rover-control",8192,nullptr,3,nullptr,1)!=pdPASS) {
    Serial.println("Control task failed");while(true)delay(1000);
  }
  server.on("/", HTTP_GET, [] { server.send_P(200, "text/html", PAGE); });
  server.on("/forward", HTTP_GET, [] { respondDrive(speedValue, speedValue, "forward"); });
  server.on("/backward", HTTP_GET, [] { respondDrive(-speedValue, -speedValue, "backward"); });
  server.on("/left", HTTP_GET, [] { respondDrive(-speedValue, speedValue, "left"); });
  server.on("/right", HTTP_GET, [] { respondDrive(speedValue, -speedValue, "right"); });
  server.on("/stop", HTTP_GET, [] { stopMotors(); server.send(200, "text/plain", "stopped"); });
  server.on("/api/capabilities", HTTP_GET, [] {
    server.send(200, "application/json", "{\"signed_wheels\":true,\"lease_ms\":600,\"onboard_motion\":1,\"gyro_hz\":100,\"turn_lease_ms\":1500}");
  });
  server.on("/api/wheels", HTTP_POST, [] {
    if (controlView().calActive || controlView().mode==OnboardMotion::Turn || controlView().mode==OnboardMotion::Hold) { server.send(409,"application/json","{\"error\":\"Automatic motion active; press STOP first\"}"); return; }
    int a = 0, b = 0;
    if (!server.hasArg("a") || !server.hasArg("b") ||
        !parseWheelDuty(server.arg("a"), a) || !parseWheelDuty(server.arg("b"), b)) {
      stopMotors();
      server.send(400, "application/json", "{\"error\":\"Expected signed a and b duty from -255 to 255\"}");
      return;
    }
    drive(a, b, "autonomous");
    server.send(200, "application/json", String("{\"a\":") + a + ",\"b\":" + b + "}");
  });
  server.on("/speed", HTTP_GET, [] {
    if (server.hasArg("value")) speedValue = constrain(server.arg("value").toInt(), 80, 255);
    server.send(200, "text/plain", String(speedValue));
  });
  server.on("/api/status", HTTP_GET, [] {
    server.send(200, "application/json", String("{\"motion\":\"") + controlView().reason + "\",\"speed\":" + speedValue + "}");
  });
  server.on("/api/lidar/start", HTTP_POST, [] {
    submit({LidarOn});
    server.send(200, "application/json", "{\"running\":true}");
  });
  server.on("/api/lidar/stop", HTTP_POST, [] {
    submit({LidarOff});
    server.send(200, "application/json", "{\"running\":false}");
  });
  server.on("/api/lidar/status", HTTP_GET, [] {
    auto scan=scanView();auto v=controlView();
    int points = 0;
    for (const uint16_t value : scan.mm) if (value != 0) ++points;
    String json = String("{\"running\":") + (v.lidarRunning ? "true" : "false") +
      ",\"rpm\":" + String(v.lidarRpm, 0) + ",\"pwm\":" + v.lidarDuty +
      ",\"good\":" + v.good + ",\"bad\":" + v.bad +
      ",\"bytes\":" + v.bytes + ",\"headers\":" + v.headers +
      ",\"index_errors\":" + v.indexErrors +
      ",\"points\":" + points + ",\"fault\":\"" + v.lidarFault + "\"}";
    server.send(200, "application/json", json);
  });
  server.on("/api/lidar/scan", HTTP_GET, [] {
    auto scan=scanView();
    String json;
    json.reserve(2200);
    json = "[";
    for (int i = 0; i < 360; ++i) {
      if (i) json += ',';
      json += scan.mm[i];
    }
    json += ']';
    server.send(200, "application/json", json);
  });
  server.on("/api/lidar/revolution", HTTP_GET, [] {
    auto scan=scanView();
    if (!scan.seq) {
      server.send(503, "application/json", "{\"error\":\"no complete revolution yet\"}");
      return;
    }
    server.send(200, "application/json", recordJson(scan));
  });
  server.on("/api/records/status", HTTP_GET, [] {
    portENTER_CRITICAL(&sharedMux);uint32_t bytes=logBytes;portEXIT_CRITICAL(&sharedMux);
    String json = String("{\"storage_ok\":") + (storageReady ? "true" : "false") +
      ",\"log_bytes\":" + bytes + ",\"boot_id\":" + bootId +
      ",\"seq\":" + scanView().seq + ",\"dropped_log_scans\":" + controlView().dropped + ",\"write_errors\":" + storageErrors + "}";
    server.send(200, "application/json", json);
  });
  server.on("/api/records", HTTP_GET, [] {
    if (controlView().moving || controlView().calActive) { server.send(503,"application/json","{\"error\":\"Log download paused while motors are active\"}"); return; }
    StorageLock lock(0);
    if(!lock.held){server.send(503,"application/json","{\"error\":\"Log writer busy; retry later\"}");return;}
    if (!storageReady) {
      server.send(503, "application/json", "{\"error\":\"microSD unavailable\"}");
      return;
    }
    File log = SD_MMC.open(LOG_PATH, FILE_READ);
    if (!log) {
      server.sendHeader("X-Next-Offset", "0");
      server.send(200, "application/x-ndjson", "");
      return;
    }
    uint32_t offset = server.hasArg("offset") ? strtoul(server.arg("offset").c_str(), nullptr, 10) : 0;
    if (offset > log.size()) {
      log.close();
      server.send(416, "application/json", "{\"error\":\"offset exceeds log size\"}");
      return;
    }
    log.seek(offset);
    String body;
    body.reserve(12000);
    for (int i = 0; i < 4 && log.available(); ++i) {
      const uint32_t lineStart = log.position();
      String line = log.readStringUntil('\n');
      const uint32_t lineEnd = log.position();
      log.seek(lineEnd - 1);
      const bool complete = log.read() == '\n';
      if (!complete || line.length() > 4000) {
        log.seek(lineStart); // never acknowledge an unfinished record
        break;
      }
      body += line;
      body += '\n';
    }
    server.sendHeader("X-Next-Offset", String(log.position()));
    log.close();
    server.send(200, "application/x-ndjson", body);
  });
  server.on("/api/environment", HTTP_GET, [] {
    server.send(200, "application/json", environmentJson());
  });
  server.on("/api/imu", HTTP_GET, [] {
    server.send(200, "application/json", imuJson());
  });
  setupControlRoutes();
  if(xTaskCreatePinnedToCore(storageTask,"rover-storage",8192,nullptr,1,nullptr,0)!=pdPASS) {
    Serial.println("Storage task failed");while(true)delay(1000);
  }
  server.begin();
  Serial.println("Wheel pins: IN1=GPIO1, IN2=GPIO2, IN3=GPIO41, IN4=GPIO42");
  Serial.println("LiDAR: TX->GPIO14, driver gate->GPIO47, shared GND, regulated 5V");
  Serial.println("DHT11 data=GPIO21; MPU6050 SDA=GPIO3, SCL=GPIO48 (not GPIO46)");
  Serial.println("Complete scans: /api/lidar/revolution; stored backlog: /api/records?offset=0");
}

void loop() {
  server.handleClient();
  auto v=controlView();
  static uint32_t savedVersion=0;
  if(v.calVersion!=savedVersion) {
    savedVersion=v.calVersion;
    turnPreferences.putBool("valid",false);
    bool ok=turnPreferences.putFloat("bias",v.bias)==sizeof(float);
    ok &= turnPreferences.putFloat("left",v.leftRate)==sizeof(float);
    ok &= turnPreferences.putFloat("right",v.rightRate)==sizeof(float);
    ok &= turnPreferences.putInt("sign",v.polarity)==sizeof(int);
    calibrationSaved=ok && turnPreferences.putBool("valid",true)==sizeof(bool);
  }
  if(WiFi.getMode()==WIFI_STA && WiFi.status()!=WL_CONNECTED && millis()-lastWifiReconnectMs>2000){lastWifiReconnectMs=millis();WiFi.reconnect();}
  delay(1);
}

#include "ControlRuntime.h"
