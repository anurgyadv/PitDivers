#include <Arduino.h>
#include <ESPmDNS.h>
#include <WebServer.h>
#include <WebSocketsServer.h>
#include <WiFi.h>

#include "motor_control.h"
#include "web_page.h"

#if __has_include("secrets.h")
#include "secrets.h"
#endif

#ifndef WIFI_SSID
#define WIFI_SSID "YOUR_HOME_WIFI_NAME"
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "YOUR_HOME_WIFI_PASSWORD"
#endif

WebServer webServer(80);
WebSocketsServer webSocket(84);

constexpr uint32_t MOTOR_WATCHDOG_MS = 1500;
uint32_t lastDriveCommandMs = 0;
constexpr uint8_t MIN_MOVING_PWM_PERCENT = 60;
uint8_t driveLevelPercent = 30;
int activeClient = -1;
const char* motionMode = "STOP";

uint8_t actualPwmPercent() {
  return MIN_MOVING_PWM_PERCENT +
         static_cast<uint16_t>(driveLevelPercent) *
             (100 - MIN_MOVING_PWM_PERCENT) / 100;
}

void sendStatus(uint8_t client) {
  const int leftOutput = motors.motorADirection() == MotorDirection::Reverse
      ? -motors.leftPwmPercent() : motors.leftPwmPercent();
  const int rightOutput = motors.motorBDirection() == MotorDirection::Reverse
      ? -motors.rightPwmPercent() : motors.rightPwmPercent();
  char response[96];
  snprintf(response, sizeof(response),
           "STATE LEFT=%d RIGHT=%d LEVEL=%u%% MAXPWM=%u%% MODE=%s",
           leftOutput, rightOutput, driveLevelPercent, actualPwmPercent(), motionMode);
  webSocket.sendTXT(client, response);
}

uint8_t joystickPwm(int command, uint8_t maximumPwm) {
  const int magnitude = abs(constrain(command, -100, 100));
  if (magnitude < 5) return 0;
  return MIN_MOVING_PWM_PERCENT +
         static_cast<uint16_t>(magnitude) *
             (maximumPwm - MIN_MOVING_PWM_PERCENT) / 100;
}

MotorDirection joystickDirection(int command) {
  if (command >= 5) return MotorDirection::Forward;
  if (command <= -5) return MotorDirection::Reverse;
  return MotorDirection::Stopped;
}

void handleCommand(uint8_t client, const String& message) {
  if (client != activeClient) return;

  if (message.startsWith("V")) {
    driveLevelPercent = constrain(message.substring(1).toInt(), 0, 100);
    sendStatus(client);
    return;
  }

  const uint8_t pwm = actualPwmPercent();
  if (message.startsWith("J")) {
    const int comma = message.indexOf(',');
    if (comma < 2) return;
    const int leftCommand = constrain(message.substring(1, comma).toInt(), -100, 100);
    const int rightCommand = constrain(message.substring(comma + 1).toInt(), -100, 100);
    motors.driveIndependent(
        joystickDirection(leftCommand), joystickDirection(rightCommand),
        joystickPwm(leftCommand, pwm), joystickPwm(rightCommand, pwm));
    motionMode = "JOYSTICK";
  } else if (message == "F") {
    motors.forward(pwm); motionMode = "FORWARD";
  } else if (message == "B") {
    motors.backward(pwm); motionMode = "REVERSE";
  } else if (message == "L") {
    motors.left(pwm); motionMode = "PIVOT_LEFT";
  } else if (message == "R") {
    motors.right(pwm); motionMode = "PIVOT_RIGHT";
  } else if (message == "TFL") {
    motors.testWheel(TestWheel::FrontLeft, pwm); motionMode = "TEST_FL";
  } else if (message == "TFR") {
    motors.testWheel(TestWheel::FrontRight, pwm); motionMode = "TEST_FR";
  } else if (message == "TRL") {
    motors.testWheel(TestWheel::RearLeft, pwm); motionMode = "TEST_RL";
  } else if (message == "TRR") {
    motors.testWheel(TestWheel::RearRight, pwm); motionMode = "TEST_RR";
  } else if (message == "S") {
    motors.stop(); motionMode = "STOP";
  } else if (message == "?") {
    sendStatus(client); return;
  } else {
    return;
  }

  lastDriveCommandMs = millis();
  sendStatus(client);
}

void onWebSocketEvent(uint8_t client, WStype_t event, uint8_t* payload, size_t length) {
  switch (event) {
    case WStype_CONNECTED:
      if (activeClient >= 0) {
        webSocket.sendTXT(client, "BUSY: another controller is connected");
        webSocket.disconnect(client);
        return;
      }
      activeClient = client;
      motors.stop();
      lastDriveCommandMs = millis();
      webSocket.sendTXT(client, "READY");
      sendStatus(client);
      break;

    case WStype_DISCONNECTED:
      if (activeClient == client) {
        motors.stop();
        activeClient = -1;
      }
      break;

    case WStype_TEXT:
      if (length > 0) {
        String message;
        message.reserve(length);
        for (size_t i = 0; i < length; ++i) message += static_cast<char>(payload[i]);
        message.trim();
        handleCommand(client, message);
      }
      break;

    default:
      break;
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);

  if (!motors.begin()) {
    Serial.println("PWM setup failed; motors disabled.");
    while (true) delay(1000);
  }

  if (strcmp(WIFI_SSID, "YOUR_HOME_WIFI_NAME") == 0) {
    Serial.println("Set WIFI_SSID and WIFI_PASSWORD in secrets.h first.");
    while (true) delay(1000);
  }

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("Connecting to Wi-Fi: %s", WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    motors.stop();
    delay(500);
    Serial.print('.');
  }
  Serial.println();

  if (MDNS.begin("pitdivers")) {
    MDNS.addService("http", "tcp", 80);
  } else {
    Serial.println("mDNS name failed; use the numeric IP shown below.");
  }

  webServer.on("/", HTTP_GET, [] {
    webServer.send_P(200, "text/html; charset=utf-8", CONTROL_PAGE);
  });
  webServer.onNotFound([] {
    webServer.send(404, "text/plain", "Not found");
  });
  webServer.begin();

  webSocket.begin();
  webSocket.onEvent(onWebSocketEvent);

  Serial.println();
  Serial.println("PitDivers motor web control ready");
  Serial.printf("Connected to: %s\n", WIFI_SSID);
  Serial.printf("Open: http://%s/\n", WiFi.localIP().toString().c_str());
  Serial.println("Or try: http://pitdivers.local/");
  Serial.println("74HC595: DATA=1 CLOCK=2 LATCH=48");
  Serial.println("Left PWM=19 (both left enable pins)");
  Serial.println("Right PWM=20 (both right enable pins)");
  Serial.println("Commands: forward, reverse, pivot left/right, wheel tests, stop");
}

void loop() {
  webSocket.loop();
  webServer.handleClient();

  const bool moving = motors.motorADirection() != MotorDirection::Stopped ||
                      motors.motorBDirection() != MotorDirection::Stopped;
  if (moving && millis() - lastDriveCommandMs > MOTOR_WATCHDOG_MS) {
    motors.stop();
    motionMode = "STOP";
    if (activeClient >= 0) sendStatus(static_cast<uint8_t>(activeClient));
    Serial.println("Motor watchdog stopped the rover");
  }

  delay(3);
}
