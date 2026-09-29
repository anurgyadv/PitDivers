#pragma once
#include <cstdint>
enum ControlKind { StopControl, ManualControl, CalibrateControl, CalibrationHeartbeat,
                   TurnControl, HoldControl, TurnHeartbeat, LidarOn, LidarOff };
struct ControlRequest { ControlKind kind; uint32_t id=0; float angle=0; int a=0,b=0; int front=192; };
struct ScanRecord {
  uint32_t seq=0,start=0,end=0; uint16_t mm[360]={};
  float rpm=0,accel[3]={},gyro[3]={},temperature=0,humidity=0;
  uint32_t imuAt=0,environmentAt=0;
  bool imuOK=false,environmentOK=false;
};
struct ControlView {
  int mode=0,a=0,b=0,calPhase=0,polarity=1;
  uint32_t id=0,at=0,imuAt=0,calVersion=0,dropped=0;
  bool ready=false,imuOK=false,calActive=false,moving=false;
  float yaw=0,target=0,bias=0,leftRate=0,rightRate=0;
  float accel[3]={},gyro[3]={},imuTemperature=0;
  const char* reason="Stopped";
  const char* calReason="Calibrate turns before gyro navigation";
  bool lidarRunning=false;
  int lidarDuty=0;
  float lidarRpm=0;
  uint32_t good=0,bad=0,bytes=0,headers=0,indexErrors=0;
  const char* lidarFault="stopped";
};
