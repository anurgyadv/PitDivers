#pragma once
#include <cmath>
#include <cstdint>

// Pure state machine: caller supplies fresh IMU samples and enforces drive ownership.
struct TurnCalibration {
  enum Phase { Idle, Bias, Left, Settle, Right, Done, Failed } phase = Idle;
  const char* reason = "Not calibrated";
  uint32_t since=0, previous=0, heartbeat=0;
  uint32_t levelBadMs=0;
  unsigned samples=0;
  double sum=0, sum2=0;
  float bias=0, angle=0, leftRate=0, rightRate=0, leftAngle=0, rightAngle=0;
  int yawSign=1;
  bool active() const { return phase>=Bias && phase<=Right; }
  int duty() const { return phase==Left ? -255 : phase==Right ? 255 : 0; }
  void fail(const char* why) { phase=Failed; reason=why; }
  void start(uint32_t now) { *this=TurnCalibration(); phase=Bias; since=previous=heartbeat=now; reason="Keep rover still: measuring gyro bias"; }
  void tick(uint32_t now, float z, float az, bool clear, bool connected) {
    if (!active()) return;
    const uint32_t gap=now-previous; previous=now;
    if (!connected || now-heartbeat>1500) { fail("Connection or calibration heartbeat lost"); return; }
    if (!clear) { fail("Need fresh LiDAR and 45 cm clearance around rover"); return; }
    if (gap>100 || !std::isfinite(z) || !std::isfinite(az) || std::fabs(z)>240) { fail("Gyro stale, invalid or saturated"); return; }
    // Instantaneous acceleration includes motor-start vibration, not just gravity.
    // Stay strict while measuring bias; require 150 ms of moderate deviation
    // during motion, but stop immediately for a large disturbance.
    const float vertical=std::fabs(az);
    if(vertical<.85f || vertical>1.15f) {
      levelBadMs+=gap;
      if(phase==Bias || vertical<.5f || vertical>1.5f || levelBadMs>=150) {
        fail("IMU Z axis must be vertical; keep rover level");return;
      }
    } else levelBadMs=0;
    if (phase==Bias) {
      if (std::fabs(z)>5) { fail("Rover moved during stationary calibration"); return; }
      sum+=z; sum2+=z*z; ++samples;
      if (now-since>=3000 && samples>=200) {
        if (sum2/samples-(sum/samples)*(sum/samples)>.25) { fail("Keep rover still during bias measurement"); return; }
        bias=sum/samples; phase=Left; since=now; angle=0; reason="Measuring left turn (up to 30 degrees)";
      }
      return;
    }
    if (phase==Settle) {
      if (now-since>=700) { phase=Right; since=now; angle=0; reason="Measuring right turn (up to 30 degrees)"; }
      return;
    }
    angle+=(z-bias)*(gap/1000.0f);
    if (phase==Right && std::fabs(angle)>5 && angle*yawSign>0) { fail("Left and right produced the same gyro direction"); return; }
    if (std::fabs(angle)>=30) {
      float rate=std::fabs(angle)/((now-since)/1000.0f);
      if (phase==Left) { leftAngle=angle; leftRate=rate; yawSign=angle>0?1:-1; phase=Settle; since=now; reason="Stopped: settling before right turn"; }
      else { rightAngle=angle; rightRate=rate; phase=Done; reason="Surface turn measurements saved"; }
    } else if (now-since>=2500) fail("Turn too slow or stalled on this surface");
  }
};
