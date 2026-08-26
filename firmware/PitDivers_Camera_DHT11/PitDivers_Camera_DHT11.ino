/**
 * PitDivers ESP32-S3 camera and DHT11 firmware.
 *
 * Combines Freenove's Camera Web Server and DHT11 examples so one uploaded
 * application owns both devices. Camera endpoints remain on ports 80/81 and
 * environmental telemetry is exposed as JSON on port 82.
 */

#include "esp_camera.h"
#include <DHTesp.h>
#include <WebServer.h>
#include <WiFi.h>

#include "board_config.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Missing secrets.h. Copy secrets.example.h to secrets.h and add Wi-Fi credentials."
#endif

constexpr uint8_t DHT_PIN = 21;
constexpr uint32_t DHT_READ_INTERVAL_MS = 2000;
constexpr uint16_t SENSOR_HTTP_PORT = 82;

camera_config_t cameraConfig;
DHTesp dht;
WebServer sensorServer(SENSOR_HTTP_PORT);

float latestTemperatureC = NAN;
float latestHumidityPercent = NAN;
uint8_t latestDhtStatus = 255;
uint32_t lastDhtAttemptMs = 0;
uint32_t lastGoodDhtReadingMs = 0;

void startCameraServer();
bool initializeCamera();
void initializeSensorServer();
void updateDhtReading(bool forceRead = false);

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

  const bool valid = latestDhtStatus == 0 && !isnan(latestTemperatureC) &&
                     !isnan(latestHumidityPercent);
  String response;
  response.reserve(240);
  response += "{\"ok\":";
  response += (valid ? "true" : "false");
  response += ",\"sensor\":\"DHT11\"";
  response += ",\"gpio\":";
  response += String(DHT_PIN);
  response += ",\"temperature_c\":";
  response += (valid ? String(latestTemperatureC, 1) : String("null"));
  response += ",\"humidity_percent\":";
  response += (valid ? String(latestHumidityPercent, 1) : String("null"));
  response += ",\"status_code\":";
  response += String(latestDhtStatus);
  response += ",\"age_ms\":";
  response += (valid ? String(millis() - lastGoodDhtReadingMs) : String("null"));
  response += "}";

  addCorsHeaders();
  sensorServer.send(valid ? 200 : 503, "application/json", response);
}

void initializeSensorServer() {
  dht.setup(DHT_PIN, DHTesp::DHT11);

  sensorServer.on("/", HTTP_GET, []() {
    addCorsHeaders();
    sensorServer.send(
      200,
      "text/plain",
      "PitDivers sensor service\nGET /sensors\nGET /health\n"
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

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println();
  Serial.println("Starting PitDivers camera + DHT11 firmware");

  const bool cameraReady = initializeCamera();

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  WiFi.setSleep(false);
  Serial.print("Connecting to Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  while (!WiFi.STA.hasIP()) {
    delay(100);
  }
  Serial.println();
  Serial.printf("Wi-Fi connected: %s\n", WiFi.localIP().toString().c_str());

  if (cameraReady) {
    startCameraServer();
    Serial.printf("Camera page: http://%s/\n", WiFi.localIP().toString().c_str());
    Serial.printf("Camera stream: http://%s:81/stream\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("Camera unavailable; sensor service will still start.");
  }

  initializeSensorServer();
  updateDhtReading(true);
}

void loop() {
  sensorServer.handleClient();
  updateDhtReading();
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
  cameraConfig.xclk_freq_hz = 10000000;
  cameraConfig.frame_size = FRAMESIZE_SVGA;
  cameraConfig.pixel_format = PIXFORMAT_JPEG;
  cameraConfig.grab_mode = CAMERA_GRAB_LATEST;
  cameraConfig.fb_location = CAMERA_FB_IN_PSRAM;
  cameraConfig.jpeg_quality = 8;
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
