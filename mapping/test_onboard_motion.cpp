#include "../firmware/SKETCHES/freenove_room_mapping/OnboardMotion.h"
#include <cassert>
#include <iostream>
int main(){
 LocalScan clear{true,2,2,2};OnboardMotion m;
 assert(!m.turn(1,90,0));m.configure(2,1,60,60);
 assert(m.turn(1,90,0));m.tick(10,2,1,true,clear,true);assert(m.a==-255 && m.b==-255);
 float target=m.target;assert(m.turn(1,90,100));assert(m.target==target); // no reset on retry
 for(unsigned t=20;t<=1500;t+=10){m.heartbeat=t;m.tick(t,62,1,true,clear,true);}
 assert(m.mode==OnboardMotion::Done && m.a==0);assert(m.turn(1,90,1600));assert(m.mode==OnboardMotion::Done);
 m.stop();assert(!m.turn(1,90,1500));m.tick(1600,2,1,true,clear,true);assert(m.turn(2,-90,1600));m.tick(1610,2,1,true,clear,true);assert(m.a==255);
 m.tick(1620,2,1,true,LocalScan{true,2,2,.2},true);assert(m.mode==OnboardMotion::Fault && m.a==0);
 assert(!m.turn(3,20,1630));m.stop();assert(m.hold(4,10,180,1630));m.tick(1640,2,1,true,clear,true);assert(m.a==-210 && m.b==150);
 m.tick(2300,2,1,true,clear,true);assert(m.mode==OnboardMotion::Fault && m.a==0);
 m.stop();m.previous=2300;assert(m.turn(5,30,2300));
 for(unsigned t=2310;t<=3810;t+=10){m.heartbeat=t;m.tick(t,2,1,true,clear,true);}assert(m.mode==OnboardMotion::Fault);
 m.stop();m.previous=4000;assert(m.turn(6,90,4000));
 for(unsigned t=4010;t<=5510;t+=10)m.tick(t,12,1,true,clear,true);assert(m.mode==OnboardMotion::Fault);
 m.stop();m.previous=6000;assert(m.hold(7,0,-180,6000));m.tick(6010,2,1,true,LocalScan{true,2,.2,2},true);assert(m.a==0);
 m.stop();assert(m.manual(-180,180,6010));m.tick(6020,2,1,true,clear,false);assert(m.a==0 && m.mode==OnboardMotion::Fault);
 m.stop();assert(m.manual(-180,180,6020));m.tick(6030,2,1,true,LocalScan{},true);assert(m.a==-180 && m.b==180);
 // Direct manual driving needs neither LiDAR nor gyro nor calibration.
 OnboardMotion manual;
 for(auto pair : {std::pair<int,int>{-180,180},{180,-180},{255,255},{-255,-255}}) {
   assert(manual.manual(pair.first,pair.second,0));
   manual.tick(10,NAN,NAN,false,LocalScan{false,0,0,0},true);
   assert(manual.a==pair.first && manual.b==pair.second);
   manual.stop();assert(manual.a==0 && manual.b==0);
 }
 assert(manual.manual(255,255,10));manual.tick(611,0,1,true,clear,true);
 assert(manual.a==0 && manual.b==0); // lease still stops
 assert(manual.manual(-180,180,620)); // new operator command recovers expired lease
 manual.tick(630,0,1,true,clear,false);assert(manual.a==0 && manual.b==0);
 manual.tick(640,0,1,true,clear,true);assert(manual.a==0); // reconnect alone cannot restart
 OnboardMotion guarded;guarded.configure(0,1,60,60);
 assert(guarded.hold(1,0,180,0));guarded.tick(10,0,1,true,LocalScan{},true);
 assert(guarded.mode==OnboardMotion::Fault && guarded.a==0);
 m.stop();assert(!m.hold(8,NAN,180,6040));assert(!m.turn(8,INFINITY,6040));
 m.previous=6040;assert(m.turn(9,90,6040));m.tick(6100,-100,1,true,clear,true);assert(m.mode==OnboardMotion::Fault);
 m.stop();m.configure(0,1,INFINITY,60);assert(!m.calibrated);
 std::cout<<"Onboard gyro, leases, idempotency, steering and fault tests passed\n";
}
