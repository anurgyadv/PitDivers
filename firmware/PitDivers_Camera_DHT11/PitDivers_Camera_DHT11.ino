/**
 * PitDivers ESP32-S3 camera, DHT11, HC-SR04, and MPU6050 firmware.
 *
 * Combines Freenove's Camera Web Server, DHT11, and ultrasonic examples so one
 * uploaded application owns all devices. Camera endpoints remain on ports
 * 80/81 and sensor telemetry is exposed as JSON on port 82.
 */

#include "esp_camera.h"
#include "esp_system.h"
#include "esp_timer.h"
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
// GPIO 47 is camera-free and avoids the boot-strapping function on GPIO 46.
constexpr uint8_t SONAR_TRIG_PIN = 47;
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
constexpr uint8_t MPU6050_SDA_PIN = 3;
constexpr uint8_t MPU6050_SCL_PIN = 46;
constexpr uint8_t MPU6050_ADDRESS = 0x68;
// VIO estimators need substantially denser inertial data than the dashboard
// attitude display. Sampling is performed by a dedicated task so the blocking
// ultrasonic measurement cannot introduce 40+ ms holes in the IMU timeline.
constexpr uint32_t MPU6050_SAMPLE_RATE_HZ = 100;
constexpr uint32_t MPU6050_READ_INTERVAL_US = 1000000 / MPU6050_SAMPLE_RATE_HZ;
constexpr uint32_t MPU6050_SERIAL_INTERVAL_MS = 500;
constexpr size_t IMU_BUFFER_SIZE = 256;
constexpr size_t IMU_API_DEFAULT_SAMPLES = 64;
constexpr size_t IMU_API_MAX_SAMPLES = 128;

struct ImuSample {
  uint32_t sequence;
  uint64_t timestampUs;
  int16_t accelX;
  int16_t accelY;
  int16_t accelZ;
  int16_t gyroX;
  int16_t gyroY;
  int16_t gyroZ;
  int16_t temperature;
};

camera_config_t cameraConfig;
DHTesp dht;
MPU6050 mpu6050(Wire);
WebServer sensorServer(SENSOR_HTTP_PORT);

// These identifiers are also attached to camera frames in app_httpd.cpp. They
// let a recorder reject data spanning an ESP reboot and align both streams to
// the same monotonic device clock.
uint32_t pitdiversBootId = 0;
volatile uint32_t pitdiversFrameSequence = 0;

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
portMUX_TYPE imuMux = portMUX_INITIALIZER_UNLOCKED;
ImuSample imuBuffer[IMU_BUFFER_SIZE];
size_t imuWriteIndex = 0;
size_t imuSampleCount = 0;
uint32_t nextImuSequence = 1;
uint32_t imuMissedDeadlines = 0;
TaskHandle_t imuSamplingTaskHandle = nullptr;

void startCameraServer();
bool initializeCamera();
void initializeSensorServer();
void updateDhtReading(bool forceRead = false);
float readSonarDistanceCm();
void updateSonarReading(bool forceRead = false);
bool initializeMpu6050();
void updateMpu6050Reading(bool forceRead = false);
void imuSamplingTask(void *parameter);
void handleImuReadings();

void appendUint64(String &response, uint64_t value) {
  char buffer[24];
  snprintf(buffer, sizeof(buffer), "%llu", static_cast<unsigned long long>(value));
  response += buffer;
}

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

  const bool dhtValid = latestDhtStatus == 0 && !isnan(latestTemperatureC) &&
                        !isnan(latestHumidityPercent);
  const bool anySensorValid = dhtValid || latestSonarValid || latestMpuValid;
  String response;
  response.reserve(900);
  response += "{\"ok\":";
  response += (anySensorValid ? "true" : "false");
  response += ",\"boot_id\":";
  response += String(pitdiversBootId);
  response += ",\"clock_us\":";
  appendUint64(response, static_cast<uint64_t>(esp_timer_get_time()));
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
  response += ",\"imu_rate_hz\":";
  response += String(MPU6050_SAMPLE_RATE_HZ);
  response += ",\"imu_sequence\":";
  portENTER_CRITICAL(&imuMux);
  const uint32_t latestSequence = nextImuSequence - 1;
  portEXIT_CRITICAL(&imuMux);
  response += String(latestSequence);
  response += "}";

  addCorsHeaders();
  sensorServer.send(anySensorValid ? 200 : 503, "application/json", response);
}

void handleImuReadings() {
  uint32_t afterSequence = 0;
  if (sensorServer.hasArg("after")) {
    afterSequence = strtoul(sensorServer.arg("after").c_str(), nullptr, 10);
  }

  size_t limit = IMU_API_DEFAULT_SAMPLES;
  if (sensorServer.hasArg("limit")) {
    const long requested = sensorServer.arg("limit").toInt();
    if (requested > 0) {
      limit = min(static_cast<size_t>(requested), IMU_API_MAX_SAMPLES);
    }
  }

  ImuSample *batch = static_cast<ImuSample *>(malloc(limit * sizeof(ImuSample)));
  if (batch == nullptr) {
    addCorsHeaders();
    sensorServer.send(503, "application/json", "{\"ok\":false,\"error\":\"imu_buffer_allocation_failed\"}");
    return;
  }

  size_t batchCount = 0;
  uint32_t oldestSequence = 0;
  uint32_t latestSequence = 0;
  uint32_t missedDeadlines = 0;
  portENTER_CRITICAL(&imuMux);
  latestSequence = nextImuSequence - 1;
  missedDeadlines = imuMissedDeadlines;
  if (imuSampleCount > 0) {
    const size_t oldestIndex = (imuWriteIndex + IMU_BUFFER_SIZE - imuSampleCount) % IMU_BUFFER_SIZE;
    oldestSequence = imuBuffer[oldestIndex].sequence;
    for (size_t offset = 0; offset < imuSampleCount && batchCount < limit; ++offset) {
      const ImuSample &sample = imuBuffer[(oldestIndex + offset) % IMU_BUFFER_SIZE];
      if (sample.sequence > afterSequence) {
        batch[batchCount++] = sample;
      }
    }
  }
  portEXIT_CRITICAL(&imuMux);

  const bool droppedBefore = afterSequence != 0 && oldestSequence != 0 &&
                             afterSequence + 1 < oldestSequence;
  String response;
  response.reserve(420 + batchCount * 105);
  response += "{\"ok\":";
  response += (latestMpuValid ? "true" : "false");
  response += ",\"boot_id\":";
  response += String(pitdiversBootId);
  response += ",\"clock_us\":";
  appendUint64(response, static_cast<uint64_t>(esp_timer_get_time()));
  response += ",\"rate_hz\":";
  response += String(MPU6050_SAMPLE_RATE_HZ);
  response += ",\"accel_lsb_per_g\":16384.0";
  response += ",\"gyro_lsb_per_dps\":65.5";
  response += ",\"oldest_sequence\":";
  response += String(oldestSequence);
  response += ",\"latest_sequence\":";
  response += String(latestSequence);
  response += ",\"missed_deadlines\":";
  response += String(missedDeadlines);
  response += ",\"dropped_before\":";
  response += (droppedBefore ? "true" : "false");
  response += ",\"sample_fields\":[\"sequence\",\"timestamp_us\",\"accel_x_raw\",\"accel_y_raw\",\"accel_z_raw\",\"gyro_x_raw\",\"gyro_y_raw\",\"gyro_z_raw\",\"temperature_raw\"]";
  response += ",\"samples\":[";
  for (size_t index = 0; index < batchCount; ++index) {
    if (index > 0) {
      response += ',';
    }
    const ImuSample &sample = batch[index];
    response += '[';
    response += String(sample.sequence);
    response += ',';
    appendUint64(response, sample.timestampUs);
    response += ',';
    response += String(sample.accelX);
    response += ',';
    response += String(sample.accelY);
    response += ',';
    response += String(sample.accelZ);
    response += ',';
    response += String(sample.gyroX);
    response += ',';
    response += String(sample.gyroY);
    response += ',';
    response += String(sample.gyroZ);
    response += ',';
    response += String(sample.temperature);
    response += ']';
  }
  response += "]}";
  free(batch);

  addCorsHeaders();
  sensorServer.send(latestMpuValid ? 200 : 503, "application/json", response);
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
      "PitDivers DHT11 + HC-SR04 + MPU6050 sensor service\nGET /sensors\nGET /imu\nGET /health\n"
    );
  });
  sensorServer.on("/health", HTTP_GET, handleSensorHealth);
  sensorServer.on("/health", HTTP_OPTIONS, handleSensorOptions);
  sensorServer.on("/sensors", HTTP_GET, handleSensorReadings);
  sensorServer.on("/sensors", HTTP_OPTIONS, handleSensorOptions);
  sensorServer.on("/imu", HTTP_GET, handleImuReadings);
  sensorServer.on("/imu", HTTP_OPTIONS, handleSensorOptions);
  sensorServer.onNotFound([]() {
    addCorsHeaders();
    sensorServer.send(404, "application/json", "{\"ok\":false,\"error\":\"not_found\"}");
  });
  sensorServer.begin();

  if (latestMpuValid && imuSamplingTaskHandle == nullptr) {
    xTaskCreatePinnedToCore(
      imuSamplingTask,
      "pitdivers-imu",
      4096,
      nullptr,
      10,
      &imuSamplingTaskHandle,
      1
    );
  }

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
  ImuSample sample;
  sample.timestampUs = static_cast<uint64_t>(esp_timer_get_time());
  sample.accelX = mpu6050.getRawAccX();
  sample.accelY = mpu6050.getRawAccY();
  sample.accelZ = mpu6050.getRawAccZ();
  sample.gyroX = mpu6050.getRawGyroX();
  sample.gyroY = mpu6050.getRawGyroY();
  sample.gyroZ = mpu6050.getRawGyroZ();
  sample.temperature = mpu6050.getRawTemp();

  portENTER_CRITICAL(&imuMux);
  sample.sequence = nextImuSequence++;
  imuBuffer[imuWriteIndex] = sample;
  imuWriteIndex = (imuWriteIndex + 1) % IMU_BUFFER_SIZE;
  if (imuSampleCount < IMU_BUFFER_SIZE) {
    ++imuSampleCount;
  }
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
  portEXIT_CRITICAL(&imuMux);

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

void imuSamplingTask(void *parameter) {
  (void)parameter;
  int64_t nextSampleUs = esp_timer_get_time();
  while (true) {
    int64_t nowUs = esp_timer_get_time();
    if (nowUs < nextSampleUs) {
      const int64_t remainingUs = nextSampleUs - nowUs;
      if (remainingUs > 1500) {
        vTaskDelay(pdMS_TO_TICKS((remainingUs - 500) / 1000));
      } else {
        delayMicroseconds(static_cast<uint32_t>(remainingUs));
      }
      continue;
    }

    if (nowUs - nextSampleUs >= static_cast<int64_t>(MPU6050_READ_INTERVAL_US)) {
      const uint32_t missed = static_cast<uint32_t>(
        (nowUs - nextSampleUs) / MPU6050_READ_INTERVAL_US
      );
      portENTER_CRITICAL(&imuMux);
      imuMissedDeadlines += missed;
      portEXIT_CRITICAL(&imuMux);
      nextSampleUs += static_cast<int64_t>(missed) * MPU6050_READ_INTERVAL_US;
    }

    updateMpu6050Reading();
    nextSampleUs += MPU6050_READ_INTERVAL_US;
  }
}

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println();
  Serial.println("Starting PitDivers camera + DHT11 + HC-SR04 + MPU6050 firmware");
  pitdiversBootId = esp_random();

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
  updateSonarReading(true);
}

void loop() {
  sensorServer.handleClient();
  updateDhtReading();
  updateSonarReading();
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
