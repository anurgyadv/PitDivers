#pragma once

#include <Arduino.h>

enum class MotorDirection : uint8_t {
  Stopped,
  Forward,
  Reverse,
};

enum class TestWheel : uint8_t {
  FrontLeft,
  FrontRight,
  RearLeft,
  RearRight,
};

class MotorController {
 public:
  bool begin();
  void drive(MotorDirection motorA, MotorDirection motorB, uint8_t speedPercent);
  void driveIndependent(MotorDirection left, MotorDirection right,
                        uint8_t leftPwmPercent, uint8_t rightPwmPercent);
  void forward(uint8_t speedPercent);
  void backward(uint8_t speedPercent);
  void left(uint8_t speedPercent);
  void right(uint8_t speedPercent);
  void testWheel(TestWheel wheel, uint8_t speedPercent);
  void stop();

  MotorDirection motorADirection() const { return motorADirection_; }
  MotorDirection motorBDirection() const { return motorBDirection_; }
  uint8_t leftPwmPercent() const { return leftPwmPercent_; }
  uint8_t rightPwmPercent() const { return rightPwmPercent_; }

 private:
  void writeDirections(MotorDirection left, MotorDirection right);
  void writeDirectionBits(uint8_t bits);

  MotorDirection motorADirection_ = MotorDirection::Stopped;
  MotorDirection motorBDirection_ = MotorDirection::Stopped;
  uint8_t leftPwmPercent_ = 0;
  uint8_t rightPwmPercent_ = 0;
};

extern MotorController motors;
