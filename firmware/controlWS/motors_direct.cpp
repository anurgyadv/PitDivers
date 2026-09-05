// motors_direct.cpp
// See motors_direct.h for the pin map and PWM setup.

#include "motors_direct.h"

// ---------------------------------------------------------------------------
// Pin map — must match docs/GPIO_REFERENCE.md §1 (revised 5 Sept 2026).
// Change ONLY here if the wiring changes.
// ---------------------------------------------------------------------------
// Pin map matches the known-good serial bench test (two-motor L293D demo).
static const uint8_t PIN_A_IN1  = 1;    // L293D IN1  (Motor A direction bit 1)
static const uint8_t PIN_A_IN2  = 14;   // L293D IN2  (Motor A direction bit 2)
static const uint8_t PIN_A_EN   = 41;   // L293D ENA  (Motor A PWM enable)
static const uint8_t PIN_B_IN3  = 21;   // L293D IN3  (Motor B direction bit 1)
static const uint8_t PIN_B_IN4  = 47;   // L293D IN4  (Motor B direction bit 2)
static const uint8_t PIN_B_EN   = 42;   // L293D ENB  (Motor B PWM enable)

// LEDC channels — 0 and 1 are reserved for the camera's XCLK timer.
// We use 2 for Motor A, 3 for Motor B.
static const uint8_t LEDC_CH_A = 2;
static const uint8_t LEDC_CH_B = 3;

Motors motors;

Motors::Motors()
    : _leftDir(DIR_STOP), _rightDir(DIR_STOP), _speed(0)
{
}

void Motors::begin()
{
    // Direction pins as outputs, all LOW (L293D brake)
    pinMode(PIN_A_IN1, OUTPUT);
    pinMode(PIN_A_IN2, OUTPUT);
    pinMode(PIN_B_IN3, OUTPUT);
    pinMode(PIN_B_IN4, OUTPUT);
    digitalWrite(PIN_A_IN1, LOW);
    digitalWrite(PIN_A_IN2, LOW);
    digitalWrite(PIN_B_IN3, LOW);
    digitalWrite(PIN_B_IN4, LOW);

    // LEDC PWM on the EN pins, 1 kHz, 11-bit resolution.
    // ledcAttachChannel() binds a specific LEDC channel to the pin (ESP32
    // Arduino core 3.x). After this, PWM is addressed BY PIN with ledcWrite().
    ledcAttachChannel(PIN_A_EN, MOTOR_PWM_FREQ_HZ, MOTOR_PWM_RES_BITS, LEDC_CH_A);
    ledcAttachChannel(PIN_B_EN, MOTOR_PWM_FREQ_HZ, MOTOR_PWM_RES_BITS, LEDC_CH_B);

    // Start at duty = 0 (coast, both motors braked via the IN pins above)
    ledcWrite(PIN_A_EN, 0);
    ledcWrite(PIN_B_EN, 0);

    _leftDir  = DIR_STOP;
    _rightDir = DIR_STOP;
    _speed    = 0;
}

void Motors::applyDir(MotorDir dir, uint8_t in1Pin, uint8_t in2Pin)
{
    // IN1 = L293D "forward" input, IN2 = L293D "reverse" input
    // (per the L293D truth table: IN1=H,IN2=L = forward; IN1=L,IN2=H = reverse)
    switch (dir) {
        case DIR_STOP:
            digitalWrite(in1Pin, LOW);
            digitalWrite(in2Pin, LOW);
            break;
        case DIR_FORWARD:
            digitalWrite(in1Pin, HIGH);
            digitalWrite(in2Pin, LOW);
            break;
        case DIR_REVERSE:
            digitalWrite(in1Pin, LOW);
            digitalWrite(in2Pin, HIGH);
            break;
    }
}

void Motors::settleIfDriving(MotorDir leftOrRight)
{
    // If THIS motor is currently being driven (not STOP), pause briefly to
    // let the H-bridge decay before flipping IN pins. Cheap insurance.
    if (leftOrRight != DIR_STOP) {
        delay(MOTOR_DIR_SETTLE_MS);
    }
}

void Motors::drive(MotorDir leftDir, MotorDir rightDir, uint8_t speedPct)
{
    speedPct = constrain(speedPct, 0, 100);

    // Settle BEFORE flipping direction on motors that are currently driving
    if (leftDir  != _leftDir)  settleIfDriving(_leftDir);
    if (rightDir != _rightDir) settleIfDriving(_rightDir);

    // Direction pins — Motor A on (2, 21), Motor B on (44, 48)
    applyDir(leftDir,  PIN_A_IN1, PIN_A_IN2);
    applyDir(rightDir, PIN_B_IN3, PIN_B_IN4);

    // PWM on the EN pins. STOP = 0 duty (coast). FORWARD/REVERSE = speedPct.
    // Addressed by pin (see begin() note on ledcAttachChannel/ledcWrite).
    uint32_t duty = (uint32_t)speedPct * MOTOR_PWM_MAX_DUTY / 100u;
    ledcWrite(PIN_A_EN, (leftDir  == DIR_STOP) ? 0 : duty);
    ledcWrite(PIN_B_EN, (rightDir == DIR_STOP) ? 0 : duty);

    _leftDir  = leftDir;
    _rightDir = rightDir;
    _speed    = speedPct;
}

void Motors::forward(uint8_t speedPct)  { drive(DIR_FORWARD, DIR_FORWARD, speedPct); }
void Motors::backward(uint8_t speedPct) { drive(DIR_REVERSE, DIR_REVERSE, speedPct); }

void Motors::turnLeft(uint8_t speedPct)
{
    // Pivot turn: left motor stops, right motor forward
    drive(DIR_STOP, DIR_FORWARD, speedPct);
}

void Motors::turnRight(uint8_t speedPct)
{
    // Pivot turn: right motor stops, left motor forward
    drive(DIR_FORWARD, DIR_STOP, speedPct);
}

void Motors::stop()
{
    drive(DIR_STOP, DIR_STOP, 0);
}
