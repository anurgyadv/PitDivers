# Freenove ESP32-S3 wheels, LiDAR, DHT11 and MPU6050

This is a separate copy of the working wheels and LiDAR firmware. It retains L298N inputs GPIO1/2/41/42 and LiDAR RX GPIO14 / motor PWM GPIO47.

| Sensor connection | Freenove GPIO |
|---|---:|
| DHT11 data | 21 |
| MPU6050 SDA | 3 |
| MPU6050 SCL | **48** |

**Move the MPU6050 SCL wire from GPIO46 to GPIO48 before using this sketch.** GPIO46 is a boot strapping pin; the I²C pull-up can affect startup. GPIO48 is also connected to the board's RGB LED, so it may flicker while the MPU6050 is being read. GPIO3 is also a strapping pin; if startup is unreliable, move SDA to another free pin and update `IMU_SDA` in the sketch. Connect the sensor grounds to ESP32-S3 GND. Power the DHT11 and MPU6050 breakout at 3.3 V unless their specific boards provide 3.3 V level shifting; ESP32-S3 GPIOs are not 5 V tolerant.

Install **DHT sensor library for ESPx** in Arduino IDE if it is not already installed. Open `freenove_wheels_lidar_sensors.ino`, select ESP32S3 Dev Module and the Freenove COM port, then upload. The web page shows temperature, humidity, acceleration and rotation rate. JSON is available at `/api/environment`, `/api/imu`, `/api/lidar/status`, and `/api/lidar/scan`. The LiDAR motor remains off at startup and stops after five seconds without valid scan packets.
