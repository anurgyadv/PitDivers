#include "motor_control.h"

// Final four-motor wiring.
constexpr uint8_t SHIFT_DATA = 1;
constexpr uint8_t SHIFT_CLOCK = 2;
constexpr uint8_t SHIFT_LATCH = 48;
constexpr uint8_t LEFT_ENABLE = 19;
constexpr uint8_t RIGHT_ENABLE = 20;

// Q0/Q1 front-left, Q2/Q3 front-right,
// Q4/Q5 rear-left, Q6/Q7 rear-right.
constexpr uint8_t FL_FORWARD_BIT = 0;
constexpr uint8_t FL_REVERSE_BIT = 1;
constexpr uint8_t FR_FORWARD_BIT = 2;
constexpr uint8_t FR_REVERSE_BIT = 3;
constexpr uint8_t RL_FORWARD_BIT = 4;
constexpr uint8_t RL_REVERSE_BIT = 5;
constexpr uint8_t RR_FORWARD_BIT = 6;
constexpr uint8_t RR_REVERSE_BIT = 7;

constexpr uint8_t LEFT_PWM_CHANNEL = 2;
constexpr uint8_t RIGHT_PWM_CHANNEL = 3;
constexpr uint32_t PWM_FREQUENCY_HZ = 1000;
constexpr uint8_t PWM_RESOLUTION_BITS = 11;
constexpr uint32_t PWM_MAX_DUTY = (1U << PWM_RESOLUTION_BITS) - 1U;
constexpr uint16_t DIRECTION_CHANGE_DELAY_MS = 200;

// The right motors face the opposite direction on the chassis. Keep their
// wiring as drawn and correct that mirror here.
constexpr bool INVERT_RIGHT_SIDE = true;

MotorController motors;

bool MotorController::begin() {
  pinMode(SHIFT_DATA, OUTPUT);
  pinMode(SHIFT_CLOCK, OUTPUT);
  pinMode(SHIFT_LATCH, OUTPUT);
  pinMode(LEFT_ENABLE, OUTPUT);
  pinMode(RIGHT_ENABLE, OUTPUT);

  digitalWrite(LEFT_ENABLE, LOW);
  digitalWrite(RIGHT_ENABLE, LOW);
  digitalWrite(SHIFT_DATA, LOW);
  digitalWrite(SHIFT_CLOCK, LOW);
  digitalWrite(SHIFT_LATCH, LOW);

  // Clear all L293D direction inputs before PWM can be enabled.
  writeDirectionBits(0);

  const bool leftReady = ledcAttachChannel(
      LEFT_ENABLE, PWM_FREQUENCY_HZ, PWM_RESOLUTION_BITS, LEFT_PWM_CHANNEL);
  const bool rightReady = ledcAttachChannel(
      RIGHT_ENABLE, PWM_FREQUENCY_HZ, PWM_RESOLUTION_BITS, RIGHT_PWM_CHANNEL);

  if (!leftReady || !rightReady) {
    if (leftReady) ledcDetach(LEFT_ENABLE);
    if (rightReady) ledcDetach(RIGHT_ENABLE);
    return false;
  }

  stop();
  return true;
}

void MotorController::writeDirections(
    MotorDirection left, MotorDirection right) {
  const MotorDirection electricalRight = !INVERT_RIGHT_SIDE ? right :
      (right == MotorDirection::Forward ? MotorDirection::Reverse :
       right == MotorDirection::Reverse ? MotorDirection::Forward :
                                          MotorDirection::Stopped);
  uint8_t bits = 0;

  if (left == MotorDirection::Forward) {
    bits |= (1U << FL_FORWARD_BIT) | (1U << RL_FORWARD_BIT);
  } else if (left == MotorDirection::Reverse) {
    bits |= (1U << FL_REVERSE_BIT) | (1U << RL_REVERSE_BIT);
  }

  if (electricalRight == MotorDirection::Forward) {
    bits |= (1U << FR_FORWARD_BIT) | (1U << RR_FORWARD_BIT);
  } else if (electricalRight == MotorDirection::Reverse) {
    bits |= (1U << FR_REVERSE_BIT) | (1U << RR_REVERSE_BIT);
  }

  writeDirectionBits(bits);
}

void MotorController::writeDirectionBits(uint8_t bits) {
  digitalWrite(SHIFT_LATCH, LOW);
  shiftOut(SHIFT_DATA, SHIFT_CLOCK, MSBFIRST, bits);
  digitalWrite(SHIFT_LATCH, HIGH);
  Serial.printf("74HC595 direction bits: 0x%02X\n", bits);
}

void MotorController::drive(
    MotorDirection left, MotorDirection right, uint8_t speedPercent) {
  driveIndependent(left, right, speedPercent, speedPercent);
}

void MotorController::driveIndependent(
    MotorDirection left, MotorDirection right,
    uint8_t leftPwmPercent, uint8_t rightPwmPercent) {
  leftPwmPercent = constrain(leftPwmPercent, 0, 100);
  rightPwmPercent = constrain(rightPwmPercent, 0, 100);

  // Disable both H-bridges while changing direction.
  ledcWrite(LEFT_ENABLE, 0);
  ledcWrite(RIGHT_ENABLE, 0);
  if ((motorADirection_ != MotorDirection::Stopped && left != motorADirection_) ||
      (motorBDirection_ != MotorDirection::Stopped && right != motorBDirection_)) {
    delay(DIRECTION_CHANGE_DELAY_MS);
  }

  writeDirections(left, right);
  const uint32_t leftDuty = leftPwmPercent * PWM_MAX_DUTY / 100U;
  const uint32_t rightDuty = rightPwmPercent * PWM_MAX_DUTY / 100U;
  ledcWrite(LEFT_ENABLE, left == MotorDirection::Stopped ? 0 : leftDuty);
  ledcWrite(RIGHT_ENABLE, right == MotorDirection::Stopped ? 0 : rightDuty);

  motorADirection_ = left;
  motorBDirection_ = right;
  leftPwmPercent_ = left == MotorDirection::Stopped ? 0 : leftPwmPercent;
  rightPwmPercent_ = right == MotorDirection::Stopped ? 0 : rightPwmPercent;
}

void MotorController::forward(uint8_t speedPercent) {
  drive(MotorDirection::Forward, MotorDirection::Forward, speedPercent);
}

void MotorController::backward(uint8_t speedPercent) {
  drive(MotorDirection::Reverse, MotorDirection::Reverse, speedPercent);
}

void MotorController::left(uint8_t speedPercent) {
  drive(MotorDirection::Reverse, MotorDirection::Forward, speedPercent);
}

void MotorController::right(uint8_t speedPercent) {
  drive(MotorDirection::Forward, MotorDirection::Reverse, speedPercent);
}

void MotorController::testWheel(TestWheel wheel, uint8_t speedPercent) {
  speedPercent = constrain(speedPercent, 0, 100);
  ledcWrite(LEFT_ENABLE, 0);
  ledcWrite(RIGHT_ENABLE, 0);

  uint8_t bits = 0;
  bool useLeftEnable = false;
  switch (wheel) {
    case TestWheel::FrontLeft:
      bits = 1U << FL_FORWARD_BIT;
      useLeftEnable = true;
      break;
    case TestWheel::FrontRight:
      bits = 1U << (INVERT_RIGHT_SIDE ? FR_REVERSE_BIT : FR_FORWARD_BIT);
      break;
    case TestWheel::RearLeft:
      bits = 1U << RL_FORWARD_BIT;
      useLeftEnable = true;
      break;
    case TestWheel::RearRight:
      bits = 1U << (INVERT_RIGHT_SIDE ? RR_REVERSE_BIT : RR_FORWARD_BIT);
      break;
  }

  const MotorDirection nextLeft =
      useLeftEnable ? MotorDirection::Forward : MotorDirection::Stopped;
  const MotorDirection nextRight =
      useLeftEnable ? MotorDirection::Stopped : MotorDirection::Forward;
  if (motorADirection_ != nextLeft || motorBDirection_ != nextRight) {
    delay(DIRECTION_CHANGE_DELAY_MS);
  }

  writeDirectionBits(bits);
  const uint32_t duty = speedPercent * PWM_MAX_DUTY / 100U;
  ledcWrite(LEFT_ENABLE, useLeftEnable ? duty : 0);
  ledcWrite(RIGHT_ENABLE, useLeftEnable ? 0 : duty);
  motorADirection_ = nextLeft;
  motorBDirection_ = nextRight;
  leftPwmPercent_ = useLeftEnable ? speedPercent : 0;
  rightPwmPercent_ = useLeftEnable ? 0 : speedPercent;
}

void MotorController::stop() {
  drive(MotorDirection::Stopped, MotorDirection::Stopped, 0);
}
