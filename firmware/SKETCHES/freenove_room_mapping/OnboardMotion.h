#pragma once
#include <cmath>
#include <cstdint>
#include <algorithm>

struct LocalScan {
  bool fresh=false;
  float front=0, rear=0, sweep=0;
};

struct OnboardMotion {
  enum Mode { Idle, Manual, Turn, Hold, Done, Fault } mode=Idle;
  const char* reason="Stopped";
  uint32_t id=0,lastTurnId=0,previous=0,issued=0,heartbeat=0,progressAt=0,limit=0;
  int a=0,b=0,speed=0,manualA=0,manualB=0,polarity=1,turnSign=1;
  float bias=0,yaw=0,target=0,progressYaw=0,startYaw=0,leftRate=0,rightRate=0;
  bool calibrated=false;
  bool active() const { return mode==Manual || mode==Turn || mode==Hold; }
  void stop() { mode=Idle;a=b=0;reason="Stopped"; }
  void fail(const char* why) { mode=Fault;a=b=0;reason=why; }
  void configure(float offset,int sign,float left,float right) {
    bias=offset;polarity=sign;leftRate=left;rightRate=right;
    calibrated=std::isfinite(offset) && (sign==1 || sign==-1) && std::isfinite(left) && std::isfinite(right) && left>0 && right>0;
    yaw=0;
  }
  bool turn(uint32_t token,float degrees,uint32_t now) {
    if (lastTurnId==token) return id==token && (mode==Turn || mode==Done);
    if (!calibrated || active() || mode==Fault || token==0 || !std::isfinite(degrees) || std::fabs(degrees)>180 || std::fabs(degrees)<1) return false;
    id=lastTurnId=token; mode=Turn; issued=heartbeat=progressAt=now;progressYaw=yaw;target=yaw+degrees;
    turnSign=degrees>0?1:-1;startYaw=yaw;
    float rate=degrees>0?leftRate:rightRate;
    limit=uint32_t(std::min(15000.f,std::max(2500.f,1500.f+2000.f*std::fabs(degrees)/std::max(5.f,rate))));
    reason="ESP gyro turn";return true;
  }
  bool hold(uint32_t token,float correction,int duty,uint32_t now) {
    if (!calibrated || mode==Turn || mode==Fault || !std::isfinite(correction) || std::fabs(correction)>40 || std::abs(duty)>200 || duty==0) return false;
    id=token; mode=Hold;target=yaw+correction;speed=duty;issued=now;reason="ESP heading hold";return true;
  }
  bool manual(int ca,int cb,uint32_t now) {
    if(mode==Turn || mode==Hold || std::abs(ca)>255 || std::abs(cb)>255)return false;
    manualA=ca;manualB=cb;mode=Manual;issued=now;reason="Manual wheels";return true;
  }
  void tick(uint32_t now,float z,float az,bool imuOK,const LocalScan& scan,bool link) {
    uint32_t dt=now-previous;previous=now;
    bool gyroOK=imuOK && dt<=100 && std::isfinite(z) && std::fabs(z)<240 && std::isfinite(az) && std::fabs(az)>.85f && std::fabs(az)<1.15f;
    if(calibrated && gyroOK)yaw+=(z-bias)*polarity*(dt*.001f);
    if(!active()) { a=b=0; return; }
    if(!link) { fail("Wi-Fi disconnected");return; }
    // Held operator commands do not depend on mapping or obstacle sensors.
    if(mode==Manual) {
      if(now-issued>600) { fail("Manual command expired");return; }
      a=manualA;b=manualB;return;
    }
    if(!scan.fresh) { fail("LiDAR stale or insufficient returns");return; }
    if(mode!=Manual && !gyroOK) { fail("Gyro stale, tilted or invalid");return; }
    if(mode==Turn) {
      if(scan.sweep<.45f) { fail("Turn clearance below 45 cm");return; }
      if(now-heartbeat>1500) { fail("Turn heartbeat expired");return; }
      if(now-issued>limit) { fail("Turn duration exceeded");return; }
      if((yaw-startYaw)*turnSign < -5) { fail("Gyro turn direction disagrees with calibration");return; }
      if(std::fabs(yaw-progressYaw)>=.5f) { progressYaw=yaw;progressAt=now; }
      if(now-progressAt>1500) { fail("Turn stalled: no gyro rotation");return; }
      float error=target-yaw;
      // Stop early by at most 6 degrees to account for mechanical coast.
      float margin=std::min(6.f,std::max(3.f,std::fabs(z-bias)*.02f));
      // Crossing the target finishes rather than reversing at full power.
      if(error*turnSign<=margin) { mode=Done;a=b=0;reason="Gyro turn complete";return; }
      a=b=error>0?-255:255;return;
    }
    if(now-issued>600) { fail("Drive correction lease expired");return; }
    if(mode==Hold) {
      if((speed>0?scan.front:scan.rear)<.45f) { fail("Travel clearance below 45 cm");return; }
      float error=target-yaw;
      if(std::fabs(error)>45) { fail("Heading deviated too far");return; }
      int correction=int(std::max(-100.f,std::min(100.f,error*3.f)));
      a=std::max(-255,std::min(255,-speed-correction));
      b=std::max(-255,std::min(255,speed-correction));return;
    }
  }
};
