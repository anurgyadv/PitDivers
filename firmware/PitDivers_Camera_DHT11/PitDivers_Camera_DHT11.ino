/**
 * PitDivers ESP32-S3 camera, DHT11, HC-SR04, and MPU6050 firmware.
 *
 * Combines Freenove's Camera Web Server, DHT11, and ultrasonic examples so one
 * uploaded application owns all devices. Camera endpoints remain on ports
 * 80/81 and sensor telemetry is exposed as JSON on port 82.
 */

#include "esp_camera.h"
#include <DHTesp.h>
#include <MPU6050_tockn.h>
#include <WebServer.h>
#include <WiFi.h>
#include <Wire.h>

#include "board_config.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Missing secrets.h. Copy secrets.example.h to secrets.h and add Wi-Fi credentials."
#endif

constexpr uint8_t DHT_PIN = 21;
constexpr uint32_t DHT_READ_INTERVAL_MS = 2000;
// GPIO 46 is camera-free and can drive the HC-SR04 TRIG signal. It is also a
// boot-strapping pin, so the attached HC-SR04 input must not pull it HIGH while
// the ESP32-S3 is resetting or entering the serial bootloader.
constexpr uint8_t SONAR_TRIG_PIN = 46;
constexpr uint8_t SONAR_ECHO_PIN = 14;
constexpr float SONAR_MAX_DISTANCE_CM = 700.0f;
constexpr float SOUND_SPEED_CM_PER_US = 0.034f;
constexpr uint32_t SONAR_TIMEOUT_US = 42000;
// Ten readings per second keeps proximity feedback responsive without
// continuously blocking the camera/server task on pulseIn().
constexpr uint32_t SONAR_READ_INTERVAL_MS = 100;
constexpr uint16_t SENSOR_HTTP_PORT = 82;
// The original Freenove example used a conservative 10 MHz XCLK. The camera
// sensors supported by this sketch normally run at 20 MHz; together with a
// slightly lighter JPEG setting this raises MJPEG throughput while preserving
// the selected frame resolution.
constexpr uint32_t CAMERA_XCLK_HZ = 20000000;
constexpr uint8_t CAMERA_JPEG_QUALITY = 10;
constexpr uint8_t MPU6050_SDA_PIN = 41;
constexpr uint8_t MPU6050_SCL_PIN = 42;
constexpr uint8_t MPU6050_ADDRESS = 0x68;
constexpr uint32_t MPU6050_READ_INTERVAL_MS = 50;
constexpr uint32_t MPU6050_SERIAL_INTERVAL_MS = 500;

camera_config_t cameraConfig;
DHTesp dht;
MPU6050 mpu6050(Wire);
WebServer sensorServer(SENSOR_HTTP_PORT);

float latestTemperatureC = NAN;
float latestHumidityPercent = NAN;
uint8_t latestDhtStatus = 255;
uint32_t lastDhtAttemptMs = 0;
uint32_t lastGoodDhtReadingMs = 0;
float latestDistanceCm = NAN;
bool latestSonarValid = false;
uint32_t lastSonarAttemptMs = 0;
uint32_t lastGoodSonarReadingMs = 0;
bool latestMpuValid = false;
float latestAccelXG = NAN;
float latestAccelYG = NAN;
float latestAccelZG = NAN;
float latestGyroXDps = NAN;
float latestGyroYDps = NAN;
float latestGyroZDps = NAN;
float latestRollDeg = NAN;
float latestPitchDeg = NAN;
float latestYawDeg = NAN;
float latestMpuTemperatureC = NAN;
uint32_t lastMpuAttemptMs = 0;
uint32_t lastGoodMpuReadingMs = 0;
uint32_t lastMpuSerialMs = 0;

void startCameraServer();
bool initializeCamera();
void initializeSensorServer();
void updateDhtReading(bool forceRead = false);
float readSonarDistanceCm();
void updateSonarReading(bool forceRead = false);
bool initializeMpu6050();
void updateMpu6050Reading(bool forceRead = false);

IPAddress roverIP;

void addCorsHeaders() {
  sensorServer.sendHeader("Access-Control-Allow-Origin", "*");
  sensorServer.sendHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  sensorServer.sendHeader("Access-Control-Allow-Headers", "Content-Type");
  sensorServer.sendHeader("Cache-Control", "no-store");
}

void handleSensorOptions() {
  addCorsHeaders();
  sensorServer.send(204, "text/plain", "");
}

void handleSensorHealth() {
  addCorsHeaders();
  sensorServer.send(200, "application/json", "{\"ok\":true,\"service\":\"pitdivers-sensors\"}");
}

void handleSensorReadings() {
  updateDhtReading();
  updateSonarReading();
  updateMpu6050Reading();

  const bool dhtValid = latestDhtStatus == 0 && !isnan(latestTemperatureC) &&
                        !isnan(latestHumidityPercent);
  const bool anySensorValid = dhtValid || latestSonarValid || latestMpuValid;
  String response;
  response.reserve(900);
  response += "{\"ok\":";
  response += (anySensorValid ? "true" : "false");
  response += ",\"sensor\":\"DHT11\"";
  response += ",\"dht_ok\":";
  response += (dhtValid ? "true" : "false");
  response += ",\"gpio\":";
  response += String(DHT_PIN);
  response += ",\"temperature_c\":";
  response += (dhtValid ? String(latestTemperatureC, 1) : String("null"));
  response += ",\"humidity_percent\":";
  response += (dhtValid ? String(latestHumidityPercent, 1) : String("null"));
  response += ",\"status_code\":";
  response += String(latestDhtStatus);
  response += ",\"age_ms\":";
  response += (dhtValid ? String(millis() - lastGoodDhtReadingMs) : String("null"));
  response += ",\"sonar_ok\":";
  response += (latestSonarValid ? "true" : "false");
  response += ",\"distance_cm\":";
  response += (latestSonarValid ? String(latestDistanceCm, 1) : String("null"));
  response += ",\"sonar_trig_gpio\":";
  response += String(SONAR_TRIG_PIN);
  response += ",\"sonar_echo_gpio\":";
  response += String(SONAR_ECHO_PIN);
  response += ",\"sonar_age_ms\":";
  response += (latestSonarValid ? String(millis() - lastGoodSonarReadingMs) : String("null"));
  response += ",\"mpu_ok\":";
  response += (latestMpuValid ? "true" : "false");
  response += ",\"mpu_address\":\"0x68\"";
  response += ",\"mpu_sda_gpio\":";
  response += String(MPU6050_SDA_PIN);
  response += ",\"mpu_scl_gpio\":";
  response += String(MPU6050_SCL_PIN);
  response += ",\"accel_g\":{\"x\":";
  response += (latestMpuValid ? String(latestAccelXG, 3) : String("null"));
  response += ",\"y\":";
  response += (latestMpuValid ? String(latestAccelYG, 3) : String("null"));
  response += ",\"z\":";
  response += (latestMpuValid ? String(latestAccelZG, 3) : String("null"));
  response += "}";
  response += ",\"gyro_dps\":{\"x\":";
  response += (latestMpuValid ? String(latestGyroXDps, 2) : String("null"));
  response += ",\"y\":";
  response += (latestMpuValid ? String(latestGyroYDps, 2) : String("null"));
  response += ",\"z\":";
  response += (latestMpuValid ? String(latestGyroZDps, 2) : String("null"));
  response += "}";
  response += ",\"tilt_deg\":{\"roll\":";
  response += (latestMpuValid ? String(latestRollDeg, 2) : String("null"));
  response += ",\"pitch\":";
  response += (latestMpuValid ? String(latestPitchDeg, 2) : String("null"));
  response += ",\"yaw\":";
  response += (latestMpuValid ? String(latestYawDeg, 2) : String("null"));
  response += "}";
  response += ",\"mpu_temperature_c\":";
  response += (latestMpuValid ? String(latestMpuTemperatureC, 2) : String("null"));
  response += ",\"mpu_age_ms\":";
  response += (latestMpuValid ? String(millis() - lastGoodMpuReadingMs) : String("null"));
  response += "}";

  addCorsHeaders();
  sensorServer.send(anySensorValid ? 200 : 503, "application/json", response);
}

void initializeSensorServer() {
  dht.setup(DHT_PIN, DHTesp::DHT11);
  pinMode(SONAR_TRIG_PIN, OUTPUT);
  pinMode(SONAR_ECHO_PIN, INPUT);
  digitalWrite(SONAR_TRIG_PIN, LOW);
  initializeMpu6050();

  sensorServer.on("/", HTTP_GET, []() {
    addCorsHeaders();
    sensorServer.send(
      200,
      "text/plain",
      "PitDivers DHT11 + HC-SR04 + MPU6050 sensor service\nGET /sensors\nGET /health\n"
    );
  });
  sensorServer.on("/health", HTTP_GET, handleSensorHealth);
  sensorServer.on("/health", HTTP_OPTIONS, handleSensorOptions);
  sensorServer.on("/sensors", HTTP_GET, handleSensorReadings);
  sensorServer.on("/sensors", HTTP_OPTIONS, handleSensorOptions);
  sensorServer.onNotFound([]() {
    addCorsHeaders();
    sensorServer.send(404, "application/json", "{\"ok\":false,\"error\":\"not_found\"}");
  });
  sensorServer.begin();

  Serial.printf("DHT11 ready on GPIO %u\n", DHT_PIN);
  Serial.printf("HC-SR04 ready: TRIG GPIO %u | ECHO GPIO %u\n", SONAR_TRIG_PIN, SONAR_ECHO_PIN);
  Serial.printf("MPU6050 I2C: SDA GPIO %u | SCL GPIO %u | address 0x%02X\n", MPU6050_SDA_PIN, MPU6050_SCL_PIN, MPU6050_ADDRESS);
  Serial.printf("Sensor API: http://%s:%u/sensors\n", WiFi.localIP().toString().c_str(), SENSOR_HTTP_PORT);
}

void updateDhtReading(bool forceRead) {
  const uint32_t now = millis();
  if (!forceRead && now - lastDhtAttemptMs < DHT_READ_INTERVAL_MS) {
    return;
  }

  lastDhtAttemptMs = now;
  const TempAndHumidity reading = dht.getTempAndHumidity();
  latestDhtStatus = dht.getStatus();

  if (latestDhtStatus == 0 && !isnan(reading.temperature) && !isnan(reading.humidity)) {
    latestTemperatureC = reading.temperature;
    latestHumidityPercent = reading.humidity;
    lastGoodDhtReadingMs = now;
    Serial.printf(
      "DHT11 | Temperature: %.1f C | Humidity: %.1f %%\n",
      latestTemperatureC,
      latestHumidityPercent
    );
  } else {
    Serial.printf("DHT11 read failed with status %u\n", latestDhtStatus);
  }
}

float readSonarDistanceCm() {
  digitalWrite(SONAR_TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(SONAR_TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(SONAR_TRIG_PIN, LOW);

  const unsigned long echoDurationUs = pulseIn(SONAR_ECHO_PIN, HIGH, SONAR_TIMEOUT_US);
  if (echoDurationUs == 0) {
    return NAN;
  }

  const float distanceCm = echoDurationUs * SOUND_SPEED_CM_PER_US / 2.0f;
  if (distanceCm < 2.0f || distanceCm > SONAR_MAX_DISTANCE_CM) {
    return NAN;
  }
  return distanceCm;
}

void updateSonarReading(bool forceRead) {
  const uint32_t now = millis();
  if (!forceRead && now - lastSonarAttemptMs < SONAR_READ_INTERVAL_MS) {
    return;
  }

  lastSonarAttemptMs = now;
  const float distanceCm = readSonarDistanceCm();
  latestSonarValid = !isnan(distanceCm);
  if (latestSonarValid) {
    latestDistanceCm = distanceCm;
    lastGoodSonarReadingMs = millis();
    Serial.printf("HC-SR04 | Distance: %.1f cm\n", latestDistanceCm);
  } else {
    latestDistanceCm = NAN;
    Serial.println("HC-SR04 | Out of range / no echo");
  }
}

bool initializeMpu6050() {
  Wire.begin(MPU6050_SDA_PIN, MPU6050_SCL_PIN);
  Wire.setClock(400000);

  Wire.beginTransmission(MPU6050_ADDRESS);
  if (Wire.endTransmission(true) != 0) {
    latestMpuValid = false;
    Serial.println("MPU6050 not detected at I2C address 0x68");
    return false;
  }

  mpu6050.begin();
  Serial.println("MPU6050 detected. Keep the rover still while the gyro calibrates.");
  mpu6050.calcGyroOffsets(true, 500, 500);
  mpu6050.update();
  latestMpuValid = true;
  lastGoodMpuReadingMs = millis();
  return true;
}

void updateMpu6050Reading(bool forceRead) {
  const uint32_t now = millis();
  if (!forceRead && now - lastMpuAttemptMs < MPU6050_READ_INTERVAL_MS) {
    return;
  }
  lastMpuAttemptMs = now;

  Wire.beginTransmission(MPU6050_ADDRESS);
  if (Wire.endTransmission(true) != 0) {
    latestMpuValid = false;
    if (forceRead || now - lastMpuSerialMs >= MPU6050_SERIAL_INTERVAL_MS) {
      Serial.println("MPU6050 | Not detected");
      lastMpuSerialMs = now;
    }
    return;
  }

  mpu6050.update();
  latestAccelXG = mpu6050.getAccX();
  latestAccelYG = mpu6050.getAccY();
  latestAccelZG = mpu6050.getAccZ();
  latestGyroXDps = mpu6050.getGyroX();
  latestGyroYDps = mpu6050.getGyroY();
  latestGyroZDps = mpu6050.getGyroZ();
  latestRollDeg = mpu6050.getAngleX();
  latestPitchDeg = mpu6050.getAngleY();
  latestYawDeg = mpu6050.getAngleZ();
  latestMpuTemperatureC = mpu6050.getTemp();
  latestMpuValid = true;
  lastGoodMpuReadingMs = now;

  if (forceRead || now - lastMpuSerialMs >= MPU6050_SERIAL_INTERVAL_MS) {
    Serial.printf(
      "MPU6050 | Accel: %.3f %.3f %.3f g | Gyro: %.2f %.2f %.2f dps | Angle: %.1f %.1f %.1f deg\n",
      latestAccelXG,
      latestAccelYG,
      latestAccelZG,
      latestGyroXDps,
      latestGyroYDps,
      latestGyroZDps,
      latestRollDeg,
      latestPitchDeg,
      latestYawDeg
    );
    lastMpuSerialMs = now;
  }
}

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println();
  Serial.println("Starting PitDivers camera + DHT11 + HC-SR04 + MPU6050 firmware");

  const bool cameraReady = initializeCamera();

  // Try site Wi-Fi (STA) for ~25 s, fall back to rover hotspot (AP).
  // Works whether credentials are present, wrong, or absent.
  const bool hasStationCreds = WIFI_SSID[0] != '\0';

  if (hasStationCreds) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    WiFi.setSleep(false);
    Serial.print("Connecting to Wi-Fi");
    const uint32_t wifiStartMs = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - wifiStartMs < 25000) {
      delay(500);
      Serial.print(".");
    }
    Serial.println();
  }

  if (WiFi.status() == WL_CONNECTED && WiFi.STA.hasIP()) {
    roverIP = WiFi.localIP();
    Serial.printf("STA connected: %s\n", roverIP.toString().c_str());
  } else {
    Serial.println("STA unavailable — starting AP hotspot");
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASSWORD);
    roverIP = WiFi.softAPIP();   // 192.168.4.1
    Serial.printf("AP ready: SSID=%s  IP=%s\n", AP_SSID, roverIP.toString().c_str());
  }

  if (cameraReady) {
    startCameraServer();
    Serial.printf("Camera page: http://%s/\n", WiFi.localIP().toString().c_str());
    Serial.printf("Camera stream: http://%s:81/stream\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("Camera unavailable; sensor service will still start.");
  }

  initializeSensorServer();
  updateDhtReading(true);
  updateSonarReading(true);
  updateMpu6050Reading(true);
}

void loop() {
  sensorServer.handleClient();
  updateDhtReading();
  updateSonarReading();
  updateMpu6050Reading();
  delay(2);
}

bool initializeCamera() {
  cameraConfig.ledc_channel = LEDC_CHANNEL_0;
  cameraConfig.ledc_timer = LEDC_TIMER_0;
  cameraConfig.pin_d0 = Y2_GPIO_NUM;
  cameraConfig.pin_d1 = Y3_GPIO_NUM;
  cameraConfig.pin_d2 = Y4_GPIO_NUM;
  cameraConfig.pin_d3 = Y5_GPIO_NUM;
  cameraConfig.pin_d4 = Y6_GPIO_NUM;
  cameraConfig.pin_d5 = Y7_GPIO_NUM;
  cameraConfig.pin_d6 = Y8_GPIO_NUM;
  cameraConfig.pin_d7 = Y9_GPIO_NUM;
  cameraConfig.pin_xclk = XCLK_GPIO_NUM;
  cameraConfig.pin_pclk = PCLK_GPIO_NUM;
  cameraConfig.pin_vsync = VSYNC_GPIO_NUM;
  cameraConfig.pin_href = HREF_GPIO_NUM;
  cameraConfig.pin_sccb_sda = SIOD_GPIO_NUM;
  cameraConfig.pin_sccb_scl = SIOC_GPIO_NUM;
  cameraConfig.pin_pwdn = PWDN_GPIO_NUM;
  cameraConfig.pin_reset = RESET_GPIO_NUM;
  cameraConfig.xclk_freq_hz = CAMERA_XCLK_HZ;
  cameraConfig.frame_size = FRAMESIZE_SVGA;
  cameraConfig.pixel_format = PIXFORMAT_JPEG;
  cameraConfig.grab_mode = CAMERA_GRAB_LATEST;
  cameraConfig.fb_location = CAMERA_FB_IN_PSRAM;
  cameraConfig.jpeg_quality = CAMERA_JPEG_QUALITY;
  cameraConfig.fb_count = 2;

  esp_err_t error = esp_camera_init(&cameraConfig);
  if (error == ESP_ERR_NOT_SUPPORTED) {
    Serial.println("Native JPEG unsupported; falling back to RGB565 software JPEG encoding.");
    cameraConfig.pixel_format = PIXFORMAT_RGB565;
    error = esp_camera_init(&cameraConfig);
  }
  if (error != ESP_OK) {
    Serial.printf("Camera initialization failed with error 0x%x\n", error);
    return false;
  }

  sensor_t *sensor = esp_camera_sensor_get();
  if (sensor == nullptr) {
    Serial.println("Camera initialized but no sensor was returned.");
    return false;
  }

  Serial.printf("Camera PID: 0x%04X | Pixel format: %d\n", sensor->id.PID, sensor->pixformat);

  if (sensor->id.PID == OV2640_PID) {
    sensor->set_hmirror(sensor, 1);
    sensor->set_vflip(sensor, 1);
  } else if (sensor->id.PID == OV3660_PID) {
    sensor->set_hmirror(sensor, 1);
    sensor->set_vflip(sensor, 0);
  } else if (sensor->id.PID == GC2145_PID || sensor->id.PID == GC0308_PID) {
    sensor->set_hmirror(sensor, 0);
    delay(500);
    sensor->set_vflip(sensor, 0);
  } else {
    sensor->set_hmirror(sensor, 1);
    sensor->set_vflip(sensor, 0);
  }

  sensor->set_brightness(sensor, -1);
  sensor->set_saturation(sensor, 0);
  if (sensor->set_ae_level(sensor, -2) != 0) {
    Serial.println("Camera does not support the requested exposure compensation.");
  }
  return true;
}
