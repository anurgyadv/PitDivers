// Included after the sketch: all motor and sensor mutation lives in controlTask.
LocalScan localScan(uint32_t now) {
  LocalScan s;
  if(!lidarRunning || !fullScanReady || now-fullScanEndMs>350)return s;
  unsigned total=0,front=0,rear=0;s.front=s.rear=s.sweep=1000;
  for(int i=0;i<360;++i) {
    float d=fullDistanceMm[i]*.001f;
    if(d<.05f || d>6.f)continue;
    ++total;s.sweep=std::min(s.sweep,d);
    int delta=(i-rawFrontIndex+540)%360-180;
    if(std::abs(delta)<=20){++front;s.front=std::min(s.front,d);}
    if(std::abs(delta)>=160){++rear;s.rear=std::min(s.rear,d);}
  }
  s.fresh=total>=180;
  if(front<5)s.front=0;if(rear<5)s.rear=0;
  return s;
}

void controlTask(void*) {
  TickType_t wake=xTaskGetTickCount();int appliedA=0,appliedB=0;
  while(true) {
    pollLidar();
    imuValid=readImu();uint32_t now=millis();
    if(imuValid)lastImuOkMs=now;
    bool link=WiFi.getMode()!=WIFI_STA || WiFi.status()==WL_CONNECTED;
    auto scan=localScan(now);
    bool kill;
    portENTER_CRITICAL(&sharedMux);kill=emergencyStop;emergencyStop=false;portEXIT_CRITICAL(&sharedMux);
    if(kill){xQueueReset(controlQueue);onboard.fail("Control queue overflow");if(turnCalibration.active())turnCalibration.fail("Control queue overflow");}
    ControlRequest q;
    for(int n=0;n<8 && xQueueReceive(controlQueue,&q,0)==pdTRUE;++n) {
      switch(q.kind) {
        case StopControl:
          onboard.stop();if(turnCalibration.active())turnCalibration.fail("Stopped by operator");break;
        case LidarOn: startLidar();scan=LocalScan{};break;
        case LidarOff:
          stopLidar("stopped by user");onboard.stop();if(turnCalibration.active())turnCalibration.fail("LiDAR stopped");scan=LocalScan{};break;
        case CalibrateControl:
          if(!onboard.active() && !turnCalibration.active() && imuValid && scan.fresh && scan.sweep>=.45f && link) {
            onboard.stop();onboard.calibrated=false;turnCalibration.start(now);
          }
          break;
        case CalibrationHeartbeat: turnCalibration.heartbeat=now;break;
        case TurnHeartbeat: if(onboard.id==q.id && onboard.mode==OnboardMotion::Turn)onboard.heartbeat=now;break;
        case TurnControl:
          if(!turnCalibration.active()){rawFrontIndex=q.front;onboard.turn(q.id,q.angle,now);}break;
        case HoldControl:
          if(!turnCalibration.active()){rawFrontIndex=q.front;onboard.hold(q.id,q.angle,q.a,now);}break;
        case ManualControl:
          if(!turnCalibration.active()) {
            if(q.a==0 && q.b==0)onboard.stop();else onboard.manual(q.a,q.b,now);
          }
          break;
      }
    }
    int a=0,b=0;
    scan=localScan(now); // Requests may have changed the forward bearing or LiDAR state.
    if(turnCalibration.active()) {
      if(!imuValid)turnCalibration.fail("Gyro disconnected");
      else turnCalibration.tick(now,gyroDps[2],accelG[2],scan.fresh && scan.sweep>=.45f,link);
      a=b=turnCalibration.duty();
      if(turnCalibration.phase==TurnCalibration::Done) {
        onboard.configure(turnCalibration.bias,turnCalibration.yawSign,turnCalibration.leftRate,turnCalibration.rightRate);
        onboard.previous=now;++calibrationVersion;
      }
    } else {
      onboard.tick(now,gyroDps[2],accelG[2],imuValid,scan,link);a=onboard.a;b=onboard.b;
    }
    if(a!=appliedA){driveMotor(IN1,IN2,a);appliedA=a;}
    if(b!=appliedB){driveMotor(IN3,IN4,b);appliedB=b;}
    ControlView v;v.mode=onboard.mode;v.a=a;v.b=b;v.at=now;v.id=onboard.id;
    v.ready=onboard.calibrated;v.yaw=onboard.yaw;v.target=onboard.target;v.reason=onboard.reason;
    v.bias=onboard.bias;v.polarity=onboard.polarity;v.leftRate=onboard.leftRate;v.rightRate=onboard.rightRate;
    v.imuOK=imuValid;v.imuAt=lastImuOkMs;v.imuTemperature=imuTemperatureC;
    memcpy(v.accel,accelG,sizeof(v.accel));memcpy(v.gyro,gyroDps,sizeof(v.gyro));
    v.calActive=turnCalibration.active();v.calPhase=turnCalibration.phase;v.calReason=turnCalibration.reason;
    v.calVersion=calibrationVersion;v.dropped=droppedScans;v.moving=a || b;
    v.lidarRunning=lidarRunning;v.lidarDuty=lidarDuty;v.lidarRpm=lidarRpm;
    v.good=goodPackets;v.bad=badPackets;v.bytes=lidarBytes;v.headers=lidarHeaders;v.indexErrors=lidarIndexErrors;v.lidarFault=lidarFault;
    portENTER_CRITICAL(&sharedMux);sharedView=v;portEXIT_CRITICAL(&sharedMux);
    vTaskDelayUntil(&wake,pdMS_TO_TICKS(IMU_INTERVAL_MS));
  }
}

bool finiteArg(const char* name,float& value) {
  if(!server.hasArg(name))return false;
  String raw=server.arg(name);char* end=nullptr;value=strtof(raw.c_str(),&end);
  return raw.length() && *end=='\0' && isfinite(value);
}
bool idArg(uint32_t& id) {
  String raw=server.arg("id");if(!raw.length() || raw.length()>10)return false;
  for(char c:raw)if(c<'0' || c>'9')return false;
  unsigned long long parsed=strtoull(raw.c_str(),nullptr,10);
  if(!parsed || parsed>0x7fffffff)return false;id=uint32_t(parsed);return true;
}
void sendControlStatus() {
  auto v=controlView();auto scan=scanView();
  const char* modes[]={"idle","manual","turn","hold","done","fault"};
  String json=String("{\"version\":1,\"mode\":\"")+modes[v.mode]+"\",\"id\":"+v.id+
    ",\"ready\":"+(v.ready?"true":"false")+",\"reason\":\""+v.reason+"\",\"yaw_deg\":"+String(v.yaw,2)+
    ",\"target_deg\":"+String(v.target,2)+",\"a\":"+v.a+",\"b\":"+v.b+
    ",\"control_age_ms\":"+(millis()-v.at)+",\"imu_age_ms\":"+(millis()-v.imuAt)+
    ",\"scan_age_ms\":"+(millis()-scan.end)+",\"calibrating\":"+(v.calActive?"true":"false")+
    ",\"dropped_log_scans\":"+v.dropped+",\"free_heap\":"+ESP.getFreeHeap()+",\"psram_bytes\":"+ESP.getPsramSize()+"}";
  server.send(200,"application/json",json);
}
void setupControlRoutes() {
  server.on("/api/motion/status",HTTP_GET,sendControlStatus);
  server.on("/api/motion/heartbeat",HTTP_POST,[] {
    uint32_t id;
    if(!idArg(id)){server.send(400,"application/json","{\"error\":\"Invalid turn id\"}");return;}
    submit({TurnHeartbeat,id});sendControlStatus();
  });
  server.on("/api/motion",HTTP_POST,[] {
    auto v=controlView();float angle,front,duty=0;uint32_t id;
    String kind=server.arg("kind");
    if(!idArg(id) || !finiteArg("angle",angle) || !finiteArg("front",front) || front<0 || front>=360 || floorf(front)!=front ||
       (kind!="turn" && kind!="hold") || (kind=="hold" && (!finiteArg("duty",duty) || duty==0 || fabsf(duty)>200 || floorf(duty)!=duty)) ||
       fabsf(angle)>(kind=="turn"?180.f:40.f) || (kind=="turn" && fabsf(angle)<1)) {
      server.send(400,"application/json","{\"error\":\"Invalid bounded motion command\"}");return;
    }
    if(!v.ready || v.calActive || v.mode==OnboardMotion::Fault || millis()-v.at>100 || millis()-v.imuAt>100) {
      server.send(409,"application/json","{\"error\":\"Stop and calibrate gyro this boot; controller must be healthy\"}");return;
    }
    if((v.mode==OnboardMotion::Turn && (kind!="turn" || id!=v.id)) || (kind=="turn" && (v.mode==OnboardMotion::Manual || v.mode==OnboardMotion::Hold))) {
      server.send(409,"application/json","{\"error\":\"Stop existing motion first\"}");return;
    }
    submit({kind=="turn"?TurnControl:HoldControl,id,angle,int(duty),0,int(front)});
    server.send(202,"application/json",String("{\"queued\":true,\"id\":")+id+"}");
  });
  server.on("/api/turn-calibration",HTTP_GET,[] {
    auto v=controlView();
    String json=String("{\"supported\":true,\"active\":")+(v.calActive?"true":"false")+
      ",\"phase\":"+v.calPhase+",\"reason\":\""+v.calReason+"\",\"saved\":"+(calibrationSaved?"true":"false")+
      ",\"ready\":"+(v.ready?"true":"false")+",\"bias_dps\":"+String(turnPreferences.getFloat("bias",0),3)+
      ",\"left_dps\":"+String(turnPreferences.getFloat("left",0),1)+",\"right_dps\":"+String(turnPreferences.getFloat("right",0),1)+"}";
    server.send(200,"application/json",json);
  });
  server.on("/api/turn-calibration/heartbeat",HTTP_POST,[] {submit({CalibrationHeartbeat});server.send(200,"application/json","{\"ok\":true}");});
  server.on("/api/turn-calibration/start",HTTP_POST,[] {
    auto v=controlView();auto s=scanView();
    unsigned valid=0;bool clear=true;for(auto mm:s.mm){if(mm>=50 && mm<=6000){++valid;if(mm<450)clear=false;}}
    if(v.moving || v.calActive || v.mode==OnboardMotion::Turn || v.mode==OnboardMotion::Hold || !v.imuOK || millis()-v.imuAt>100 || millis()-s.end>350 || !clear || valid<180) {
      server.send(409,"application/json","{\"error\":\"Stop rover; need fresh IMU, LiDAR and 45 cm clearance all around\"}");return;
    }
    submit({CalibrateControl});server.send(202,"application/json","{\"ok\":true}");
  });
}
