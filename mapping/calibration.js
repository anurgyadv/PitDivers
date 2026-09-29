// The initiating browser owns a short calibration lease; read-only tabs don't renew it.
let calibrationOwned=false,calibrationRunning=false;
let calibrationTimer;
let calibrationError='';
const calibrate=document.getElementById('calibrateTurns'),calStatus=document.getElementById('calibrationStatus');
calibrate.onclick=async()=>{
  if(!confirm('Place the rover on this surface with at least 45 cm clear around it. Keep it still for 3 seconds; it will then turn about 30° left and right at full motor duty. Start?'))return;
  calibrate.disabled=true;calibrationError='';
  try{await stopDrive();await post('/api/calibration/start');calibrationOwned=true;calibrationRunning=true;calStatus.textContent='Keep rover still: calibrating gyro…';clearTimeout(calibrationTimer);pollCalibration();}
  catch(e){calibrationError=e.message;calStatus.textContent=calibrationError;calibrate.disabled=false;post('/api/drive',{direction:'stop'}).catch(()=>{});}
};
async function pollCalibration(){
  try{
    if(calibrationOwned)await post('/api/calibration/heartbeat');
    const r=await fetch('/api/calibration');const c=await r.json();if(!r.ok)throw Error(c.error||'Calibration unavailable');
    calibrationRunning=!!c.active;if(!c.active)calibrationOwned=false;
    calibrate.disabled=c.active||['active','paused'].includes(state?.mission?.state)||busy;
    calStatus.textContent=(!c.active&&calibrationError)?calibrationError:c.reason+(c.saved?` · Saved: left ${c.left_dps}°/s, right ${c.right_dps}°/s at 255 PWM`:'');
    if(c.active){document.querySelectorAll('[data-dir],#go,#scan,#finish,#enablePad').forEach(b=>b.disabled=true);}
  }catch(e){calibrationError=e.message;calStatus.textContent=calibrationError;if(calibrationOwned)post('/api/drive',{direction:'stop'}).catch(()=>{});calibrationOwned=false;calibrate.disabled=false;}
  calibrationTimer=setTimeout(pollCalibration,calibrationOwned||calibrationRunning?400:10000);
}
function stopCalibration(){if(calibrationOwned){calibrationOwned=false;post('/api/drive',{direction:'stop'}).catch(()=>{});}}
window.addEventListener('blur',stopCalibration);
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopCalibration();});
pollCalibration();
