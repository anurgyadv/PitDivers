// motors_direct.h
// -----------------------------------------------------------------------------
// Pit Divers — direct GPIO motor driver for the L293D on the Freenove
// ESP32-S3 WROOM GPIO Extension Board (FNK0082).
//
// This driver is INDEPENDENT of the 74HC595 shift-register path in
// firmware/2026-09-03-motors/. It drives the L293D's 6 control pins
// directly from the S3, using LEDC PWM on the two EN pins for speed
// control. Use this driver for the workshop demo and for any build
// where the 595 chain is not on the bench.
//
// The 595-based driver is the v2 production migration and lives in
// firmware/2026-09-03-motors/motors.h. To swap, change ONE #include
// and rebuild — the public API is identical (see below).
//
// ============================================================================
//  PIN MAP — see docs/GPIO_REFERENCE.md §1 (revised 5 Sept 2026)
// ============================================================================
//   L293D IN1  <- ESP32-S3 GPIO 2    (Motor A direction bit 1)
//   L293D IN2  <- ESP32-S3 GPIO 21   (Motor A direction bit 2)  [reclaimed from DHT11]
//   L293D ENA  <- ESP32-S3 GPIO 47   (Motor A PWM enable)        [LEDC channel 2]
//   L293D IN3  <- ESP32-S3 GPIO 44   (Motor B direction bit 1)  [reclaimed from UART0 RX]
//   L293D IN4  <- ESP32-S3 GPIO 48   (Motor B direction bit 2)
//   L293D ENB  <- ESP32-S3 GPIO 43   (Motor B PWM enable)        [LEDC channel 3]  [reclaimed from UART0 TX]
//
//  Serial debug: moved from UART0 (43/44) to USB-OTG via Serial.begin(115200, SERIAL_USB).
//
//  Sensors (camera DHT11, sonar, MPU) remain on their original GPIOs EXCEPT
//  DHT11, which moved from GPIO 21 to GPIO 1 — see docs/GPIO_REFERENCE.md §1.
//
// ============================================================================
//  PWM SETUP (LEDC)
// ============================================================================
//   Channels 0 and 1 are RESERVED for the camera's XCLK timer on S3-A.
//   We use channels 2 and 3 for ENA and ENB respectively.
//   Frequency: 1 kHz  (high enough to be inaudible, low enough for L293D)
//   Resolution: 11 bits (max duty 2047) — gives 0..100% in 2048 steps
//   Direction-change pause: 200 ms (lets the H-bridge settle before re-energising)
//   Auto-stop: 3 seconds (watchdog — see controlWS.ino loop)
// ============================================================================

#ifndef PITDIVERS_MOTORS_DIRECT_H
#define PITDIVERS_MOTORS_DIRECT_H

#include <Arduino.h>

// Side enum — left / right motor
enum MotorSide : uint8_t {
    MOTOR_LEFT  = 0,
    MOTOR_RIGHT = 1,
};

// Direction enum
enum MotorDir : uint8_t {
    DIR_STOP    = 0,   // both direction bits LOW  -> L293D brake
    DIR_FORWARD = 1,   // IN1=H, IN2=L  (motor A) or IN3=H, IN4=L (motor B)
    DIR_REVERSE = 2,   // IN1=L, IN2=H  (motor A) or IN3=L, IN4=H (motor B)
};

// PWM parameters
static const uint32_t MOTOR_PWM_FREQ_HZ = 1000;
static const uint8_t  MOTOR_PWM_RES_BITS = 11;
static const uint32_t MOTOR_PWM_MAX_DUTY = (1u << MOTOR_PWM_RES_BITS) - 1u;  // 2047
static const uint16_t MOTOR_DIR_SETTLE_MS = 200;   // pause after any dir change

class Motors {
public:
    Motors();

    // Call once in setup()
    void begin();

    // High-level: drive both wheels at independent directions and a single speed.
    // `speedPct` is 0..100, applied to whichever motor(s) are not stopped.
    void drive(MotorDir leftDir, MotorDir rightDir, uint8_t speedPct);

    // Convenience wrappers (both wheels same direction, full speed)
    void forward(uint8_t speedPct = 100);
    void backward(uint8_t speedPct = 100);
    void turnLeft(uint8_t speedPct = 100);
    void turnRight(uint8_t speedPct = 100);
    void stop();

    // Low-level access for the dead-reckoning logger (future)
    MotorDir leftDirection()  const { return _leftDir;  }
    MotorDir rightDirection() const { return _rightDir; }
    uint8_t  speedPct()       const { return _speed;    }

private:
    // Apply direction to one motor's two IN pins (active drive logic)
    void applyDir(MotorDir dir, uint8_t in1Pin, uint8_t in2Pin);

    // Direction-change settle: call BEFORE changing IN pins if a motor is
    // currently driving. Cheap insurance for the L293D.
    void settleIfDriving(MotorDir currentDir);

    MotorDir _leftDir;
    MotorDir _rightDir;
    uint8_t  _speed;
};

extern Motors motors;

#endif // PITDIVERS_MOTORS_DIRECT_H
