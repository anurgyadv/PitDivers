function gamepadDirection(pad) {
  if (!pad || pad.mapping !== 'standard') return null;
  if (!pad.buttons[4]?.pressed) return null; // Hold L1 to drive.
  const x=pad.axes[0], y=pad.axes[1];
  if (!Number.isFinite(x)||!Number.isFinite(y)||Math.max(Math.abs(x),Math.abs(y))<.3) return null;
  return Math.abs(x)>Math.abs(y)?(x<0?'left':'right'):(y<0?'forward':'backward');
}
if(typeof module!=='undefined') module.exports={gamepadDirection};
if(typeof window!=='undefined') {
  let enabled=false, neutral=false, owned=false, lastId=null, stopHeld=false;
  const button=document.getElementById('enablePad'), label=document.getElementById('padStatus');
  function release(){if(owned){owned=false;stopDrive();}}
  function disable(){enabled=false;neutral=false;release();button.textContent='Enable handheld controls';}
  button.onclick=()=>{if(enabled){disable();return;} enabled=true;neutral=false;button.textContent='Disable handheld controls';};
  window.addEventListener('blur',disable);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)disable();});
  function loop(){
    try{
      if(!window.isSecureContext||!navigator.getGamepads){label.textContent='Use the trusted HTTPS address for joystick controls.';button.disabled=true;disable();return;}
      const pad=Array.from(navigator.getGamepads()).find(p=>p?.connected);
      if(!pad){release();neutral=false;lastId=null;label.textContent='Press a controller button to detect the handheld.';return;}
      if(pad.id!==lastId){release();neutral=false;lastId=pad.id;}
      if(pad.mapping!=='standard'){release();label.textContent='Controller detected, but its mapping is not standard. Use touch controls.';return;}
      const emergency=!!(pad.buttons[1]?.pressed||pad.buttons[8]?.pressed);
      if(emergency&&!stopHeld){disable();document.getElementById('stop').click();}
      stopHeld=emergency;
      if(!enabled){label.textContent='Controller detected. Enable, then hold L1 + left stick to drive. Select / right face button stops.';return;}
      if(!neutral){neutral=Math.abs(pad.axes[0])<.2&&Math.abs(pad.axes[1])<.2&&!pad.buttons[4]?.pressed;label.textContent='Centre the stick and release L1 to arm.';return;}
      if(document.hidden||!document.hasFocus()||state?.session.mode!=='mapping'||['active','paused'].includes(state?.mission.state)){
        release();label.textContent='Manual stick driving is available during room scanning.';return;
      }
      const dir=gamepadDirection(pad);
      label.textContent=dir?`Driving ${dir} · release L1 or centre stick to stop`:'Ready · hold L1 and move left stick';
      if(!dir){release();return;}
      if(!owned||wanted!==dir){owned=true;wanted=dir;pulse(++generation);}
    }catch(e){disable();label.textContent=e.message;}
    finally{requestAnimationFrame(loop);}
  }
  requestAnimationFrame(loop);
}
