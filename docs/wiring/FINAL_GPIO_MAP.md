# PitDivers final GPIO map

Final allocation for the FNK0082 ESP32-S3 WROOM N16R8 with camera, onboard SD,
DHT11, HC-SR04, MPU6050, one 74HC595, two L293D drivers and four DC motors.

| GPIO | Final use |
|---:|---|
| 1 | 74HC595 SER/DATA, pin 14 |
| 2 | 74HC595 SRCLK/CLOCK, pin 11 |
| 48 | 74HC595 RCLK/LATCH, pin 12 |
| 19 | Left PWM; pin 1 on both L293Ds |
| 20 | Right PWM; pin 9 on both L293Ds |
| 21 | DHT11 DATA |
| 47 | HC-SR04 TRIG |
| 14 | HC-SR04 ECHO through 1 kΩ/2 kΩ divider |
| 41 | MPU6050 SDA |
| 42 | MPU6050 SCL |
| 38 | Onboard SD CMD |
| 39 | Onboard SD CLK |
| 40 | Onboard SD DATA0 |

Keep GPIO43/44 free for USB-UART. Leave GPIO46 unused because it is a boot
strapping pin. GPIO35/36/37 are unavailable on the N16R8 because octal PSRAM
uses them internally.

## Camera-fixed GPIOs

| Signal | GPIO |
|---|---:|
| SIOD / SIOC | 4 / 5 |
| VSYNC / HREF / PCLK | 6 / 7 / 13 |
| XCLK | 15 |
| Y2–Y9 | 11, 9, 8, 10, 12, 18, 17, 16 |

## 74HC595 direction outputs

| Outputs | Destination |
|---|---|
| Q0 / Q1 | Front L293D IN1 / IN2, pins 2 / 7 |
| Q2 / Q3 | Front L293D IN3 / IN4, pins 10 / 15 |
| Q4 / Q5 | Rear L293D IN1 / IN2, pins 2 / 7 |
| Q6 / Q7 | Rear L293D IN3 / IN4, pins 10 / 15 |

The two left motors share speed through GPIO19 and the two right motors share
speed through GPIO20. Each motor retains its own direction bit pair.
