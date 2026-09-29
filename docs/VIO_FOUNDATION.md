# Visual-inertial odometry foundation

PitDivers records camera and MPU6050 measurements on one ESP32 monotonic clock.
This is the data foundation for a later visual-inertial odometry estimator; it
does not yet calculate a position or trajectory.

## Device streams

The firmware samples the MPU6050 at 100 Hz in a dedicated FreeRTOS task. This
keeps ultrasonic `pulseIn()` delays out of the inertial timeline. The most
recent 256 samples are retained in a ring buffer and exposed from:

```text
GET http://<rover-ip>:82/imu?after=<sequence>&limit=128
```

Each response identifies the current ESP boot, reports the monotonic device
clock, and includes sequenced raw accelerometer, gyroscope, and temperature
values. A `dropped_before` flag tells the recorder when it fell behind the ring
buffer, while `missed_deadlines` counts samples the device could not take on
schedule because a higher-priority operation delayed the IMU task.

Every MJPEG part now carries:

- `X-Timestamp-Us`: camera timestamp on the ESP clock;
- `X-Boot-Id`: identifier that changes on every reboot; and
- `X-Frame-Sequence`: increasing camera frame number.

The dashboard uses a multipart reader rather than OpenCV's stream wrapper so
these headers survive decoding.

## Capture format

Starting a normal dashboard recording now creates:

```text
data/<capture>/
├── capture.json
├── imu.csv
├── frame_000000.jpg
├── frame_000000.json
└── ...
```

`imu.csv` retains raw MPU values and adds acceleration in metres per second
squared and angular velocity in radians per second. Frame sidecars contain the
exact ESP camera timestamp, boot identifier, sequence, and latest observed IMU
sequence. `capture.json` reports recorded/dropped IMU counts and format version.

The recorder estimates the ESP-to-host monotonic clock offset from low-latency
HTTP exchanges. This is used only as a fallback with older camera firmware;
new firmware supplies the device timestamp directly in each frame header.

## Required before trajectory estimation

1. Flash the updated firmware and record stationary and handheld motion trials.
2. Measure actual IMU cadence, missing samples, timestamp jitter, and camera
   frame timing from the recorded files.
3. Calibrate camera intrinsics and distortion.
4. Calibrate the rigid camera-to-IMU transform, timing offset, and MPU noise.
5. Convert captures to the chosen estimator's dataset format and validate it
   offline before adding a live trajectory to the dashboard.

The MPU6050 and rolling-shutter camera can support a prototype, but timing,
motion blur, vibration isolation, and calibration quality will determine the
result more than the estimator choice.
