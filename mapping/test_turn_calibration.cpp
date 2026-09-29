#include "../firmware/SKETCHES/freenove_room_mapping/TurnCalibration.h"
#include <cassert>
#include <iostream>
int main() {
  TurnCalibration c; c.start(0);
  for(unsigned t=10;t<=3000;t+=10){c.heartbeat=t;c.tick(t,1,1,true,true);}
  assert(c.phase==TurnCalibration::Left && std::fabs(c.bias-1)<.001 && c.duty()==-255);
  for(unsigned t=3010;t<=3500;t+=10){c.heartbeat=t;c.tick(t,61,1,true,true);}
  assert(c.phase==TurnCalibration::Settle && c.duty()==0);
  for(unsigned t=3510;t<=4210;t+=10){c.heartbeat=t;c.tick(t,1,1,true,true);}
  for(unsigned t=4220;t<=4800 && c.active();t+=10){c.heartbeat=t;c.tick(t,-59,1,true,true);}
  assert(c.phase==TurnCalibration::Done && c.duty()==0 && c.leftRate>59 && c.rightRate>55);
  c.start(0);c.tick(101,0,1,true,true);assert(c.phase==TurnCalibration::Failed);
  c.start(0);c.tick(10,0,1,false,true);assert(c.duty()==0 && !c.active());
  c.start(0);c.tick(10,10,1,true,true);assert(!c.active());
  c.start(0);c.tick(10,0,.1,true,true);assert(!c.active());
  c.start(0);c.phase=TurnCalibration::Left;
  c.tick(10,20,.82,true,true);assert(c.active());
  c.tick(20,20,1,true,true);assert(c.active());
  for(unsigned t=30;t<=190;t+=10){c.heartbeat=t;c.tick(t,20,.82,true,true);}
  assert(!c.active() && c.duty()==0); // persistent deviation still stops
  c.start(0);c.phase=TurnCalibration::Left;c.tick(10,20,.4,true,true);
  assert(!c.active()); // large disturbance stops immediately
  c.start(0);c.tick(10,0,1,true,false);assert(!c.active());
  c.start(0);c.phase=TurnCalibration::Left;
  for(unsigned t=10;t<=2500;t+=10){c.heartbeat=t;c.tick(t,0,1,true,true);}
  assert(!c.active() && c.duty()==0);
  c.start(0);c.phase=TurnCalibration::Right;c.tick(50,200,1,true,true);assert(!c.active());
  c.start(0);for(unsigned t=10;t<=1510;t+=10)c.tick(t,0,1,true,true);assert(!c.active());
  std::cout<<"Turn calibration success, stop, sensor, timeout and direction tests passed\n";
}
