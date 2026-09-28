// Saved hallway route, supervised Go to B, and manual rover controls.
(() => {
  const card = document.createElement('section');
  card.className = 'card route-card';
  card.innerHTML = `
    <h2>Hallway route <span class="tag">SUPERVISED</span></h2>
    <p class="note">Choose a saved room and mark B. The rover can start from any localized, clear point on that map. A marks the original recording start.</p>
    <div class="row"><span>Start A</span><span id="routeStart">Choose a saved room</span></div>
    <div class="row"><span>Destination B</span><span id="routeDestination">Not marked</span></div>
    <div class="row"><span>Round trip</span><span id="routeDistance">—</span></div>
    <div class="actions" style="margin-top:12px"><button id="markDestination" disabled>Mark B on map</button><button id="clearDestination" disabled>Clear B</button></div>
    <div class="actions" style="margin-top:10px"><button id="goOneWay" disabled>Go to B</button><button id="goDestination" disabled>Go B &amp; return</button><button id="cancelMission">STOP AUTO</button></div>
    <p class="note" id="missionStatus">Start saved localization and LiDAR before driving.</p>
    <p class="note" id="routeStatus">Map selection required.</p>`;
  $('saved').closest('.card').insertAdjacentElement('afterend', card);
  const style = document.createElement('style');
  style.textContent = '.route-card .actions button{flex:1}.route-card .row span:last-child{font:11px ui-monospace,SFMono-Regular,Consolas,monospace}';
  document.head.append(style);

  let selectedId = '', savedMap = null, route = null, armed = false, down = null, missionState = 'offline', missionReady = false;
  const pointText = point => point ? `${Number(point.x_m).toFixed(2)}, ${Number(point.y_m).toFixed(2)} m` : '—';
  function render() {
    const first = savedMap?.map?.path?.[0];
    $('routeStart').textContent = first ? pointText({x_m:first[0],y_m:first[1]}) : 'Choose a saved room';
    $('routeDestination').textContent = route ? pointText(route.destination) : 'Not marked';
    $('routeDistance').textContent = route ? `${route.round_trip_m.toFixed(2)} m` : '—';
    $('markDestination').disabled = !first;
    $('markDestination').classList.toggle('active', armed);
    $('markDestination').textContent = armed ? 'Click B on map…' : 'Mark B on map';
    $('clearDestination').disabled = !route;
    $('goDestination').disabled = !route?.localization_destination || !missionReady || ['active','paused'].includes(missionState);
    $('goOneWay').disabled = $('goDestination').disabled;
    $('routeStatus').textContent = !first ? 'Map selection required.'
      : armed ? 'Click near the recorded rover path. Dragging still pans the map.'
      : route ? `B snapped ${route.snap_m.toFixed(2)} m to the recorded path. Verify the live pose and clear space before Go.`
      : 'Select Mark B, then click near the recorded rover path.';
    canvas.style.cursor = armed ? 'crosshair' : '';
  }

  async function select() {
    selectedId = $('saved').value;
    const id = selectedId;
    savedMap = null; route = null; armed = false; missionReady = false;
    render(); draw();
    if (!id) return;
    try {
      const [mapResponse, routeResponse] = await Promise.all([
        fetch(`/api/saved/map?id=${encodeURIComponent(id)}`),
        fetch(`/api/route?id=${encodeURIComponent(id)}`),
      ]);
      if (!mapResponse.ok || !routeResponse.ok) throw Error('Could not load saved room route');
      const [map, stored] = await Promise.all([mapResponse.json(), routeResponse.json()]);
      if (selectedId !== id) return;
      savedMap = map; route = stored;
      render(); draw();
    } catch (error) { toast(error.message); }
  }

  function marker(context, worldToScreen, point, label, colour) {
    const [x, y] = worldToScreen(point.x_m, point.y_m);
    context.fillStyle = colour;
    context.strokeStyle = '#0c1623';
    context.lineWidth = 2;
    context.beginPath(); context.arc(x, y, 10, 0, Math.PI * 2); context.fill(); context.stroke();
    context.fillStyle = '#102027'; context.font = 'bold 11px system-ui';
    context.textAlign = 'center'; context.textBaseline = 'middle'; context.fillText(label, x, y);
    context.textAlign = 'start'; context.textBaseline = 'alphabetic';
  }

  function drawRoute(context, worldToScreen) {
    if (!savedMap || archived?.run_id !== selectedId || !savedMap.map.path.length) return;
    context.save();
    if (route?.path?.length > 1) {
      const points = routeDisplayPath(savedMap.map.path.slice(0,route.destination.path_index+1), room);
      context.lineWidth = 4; context.strokeStyle = '#6ce1c3'; context.setLineDash([]);
      context.beginPath();
      points.forEach((point, index) => {
        const xy = worldToScreen(point[0], point[1]);
        index ? context.lineTo(xy[0], xy[1]) : context.moveTo(xy[0], xy[1]);
      });
      context.stroke();
      context.lineWidth = 2; context.strokeStyle = '#ffc978'; context.setLineDash([6, 5]);
      context.beginPath();
      [...points].reverse().forEach((point, index) => {
        const xy = worldToScreen(point[0], point[1]);
        index ? context.lineTo(xy[0] + 4, xy[1] + 4) : context.moveTo(xy[0] + 4, xy[1] + 4);
      });
      context.stroke(); context.setLineDash([]);
      const end=points[points.length-1];marker(context, worldToScreen, {x_m:end[0],y_m:end[1]}, 'B', '#ffc978');
    }
    const first = routeDisplayPath(savedMap.map.path.slice(0,1),room)[0];
    marker(context, worldToScreen, {x_m:first[0], y_m:first[1]}, 'A', '#6ce1c3');
    context.restore();
  }

  const originalDraw = draw;
  draw = function () { originalDraw(); drawRoute(ctx, worldToScreen); };
  $('saved').addEventListener('change', select);
  $('markDestination').onclick = () => { armed = !armed; render(); };
  $('clearDestination').onclick = async () => {
    try {
      await post('/api/route/clear', {id:selectedId});
      route = null; armed = false; render(); draw();
    } catch (error) { toast(error.message); }
  };
  async function refreshMission() {
    try {
      const response = await fetch('/api/mission/status');
      const data = await response.json();
      missionState = data.state;
      const now = Date.now() / 1000, network = state?.network;
      const roverFresh = network?.connected && network.lidar?.running
        && now - network.last_seen < 8 && now - network.scan_received_at < 6
        && state?.map?.tracking === 'tracking';
      missionReady = data.map_id === selectedId && data.map_ready === true
        && data.localization?.ready === true
        && data.front_m >= 0.45 && data.pose_age_s !== null && data.pose_age_s <= 0.6
        && data.scan_age_s !== null && data.scan_age_s <= 0.6 && roverFresh;
      const front = data.front_m === 0 ? ' · LiDAR forward sector blind' : '';
      const fit = data.localization?.fit?.inlier_fraction;
      const match = Number.isFinite(fit) ? ` · scan match ${Math.round(fit * 100)}%` : '';
      $('missionStatus').textContent = `${data.state.toUpperCase()} · ${data.reason}${front}${match}`;
      render();
    } catch { missionState = 'offline'; missionReady = false; $('missionStatus').textContent = 'Navigation status unavailable'; render(); }
  }
  async function startMission(roundTrip) {
    try {
      await post('/api/mission/start', {id:selectedId, round_trip:roundTrip});
      $('missionStatus').textContent = 'START REQUESTED · checking pose, LiDAR, map, and wheel firmware';
      setTimeout(refreshMission, 450);
    } catch (error) { toast(error.message); refreshMission(); }
  }
  $('goOneWay').onclick = () => startMission(false);
  $('goDestination').onclick = () => startMission(true);
  $('cancelMission').onclick = async () => {
    try { await post('/api/mission/cancel'); }
    catch (error) { toast(`STOP sent to navigation; rover response: ${error.message}`); }
    refreshMission();
  };
  setInterval(refreshMission, 750);
  refreshMission();
  canvas.addEventListener('pointerdown', event => { down = [event.clientX, event.clientY]; });
  canvas.addEventListener('pointerup', async event => {
    if (!armed || !down || !selectedId) return;
    const [startX, startY] = down;
    down = null;
    if (Math.hypot(event.clientX - startX, event.clientY - startY) > 6) return;
    const rect = canvas.getBoundingClientRect();
    const mx = event.clientX - rect.left, my = event.clientY - rect.top;
    const x_m = centre[0] + (mx - width / 2) / scale;
    const y_m = centre[1] - (my - height / 2) / scale;
    const id = selectedId;
    try {
      const clicked=routeClickSource(savedMap.map.path,room,x_m,y_m);
      const saved = await post('/api/route', {id, ...clicked});
      if (selectedId !== id) return;
      route = saved; armed = false; render(); draw();
      toast(`B saved · ${route.round_trip_m.toFixed(2)} m out and back`);
    } catch (error) { toast(error.message); }
  });
  canvas.addEventListener('pointercancel', () => { down = null; });

  // Correct the chassis's 90-degree control orientation in this dashboard.
  // Keep the ESP firmware untouched until the planned flash.
  const roverDirection = {forward:'left', right:'forward', backward:'right', left:'backward'};
  const speedControl = document.createElement('div');
  speedControl.innerHTML = `
    <label for="driveSpeedSlider" style="display:flex;justify-content:space-between;gap:8px;margin-top:12px">
      <span>Motor speed</span><strong id="driveSpeedValue">160 / 255 PWM</strong>
    </label>
    <input id="driveSpeedSlider" type="range" min="80" max="255" step="1" value="160"
      style="display:block;width:100%;margin:5px 0 0" aria-label="Motor speed PWM">
    <meter id="driveSpeedMeter" min="0" max="255" value="160" style="width:100%;height:13px"></meter>
    <p class="note" id="driveSpeedStatus">Open controls to read the rover's current speed.</p>`;
  document.querySelector('.dpad').insertAdjacentElement('afterend', speedControl);
  const speedSlider = $('driveSpeedSlider');
  const speedStatus = $('driveSpeedStatus');
  function showSpeed(value) {
    speedSlider.value = value;
    $('driveSpeedValue').textContent = `${value} / 255 PWM`;
    $('driveSpeedMeter').value = value;
  }
  async function readSpeed() {
    speedStatus.textContent = 'Reading rover speed…';
    try {
      const response = await fetch('/api/drive/status');
      if (!response.ok) throw Error('Rover unavailable');
      const data = await response.json();
      showSpeed(data.speed);
      speedStatus.textContent = 'Ready · STOP button still stops the motors';
    } catch {
      speedStatus.textContent = 'Rover offline · speed not confirmed';
    }
  }
  speedControl.closest('details').addEventListener('toggle', event => {
    if (event.target.open) readSpeed();
  });
  let speedTimer = null, speedBusy = false, nextSpeed = null;
  async function sendLatestSpeed() {
    if (speedBusy) return;
    speedBusy = true;
    try {
      while (nextSpeed !== null) {
        const value = nextSpeed;
        nextSpeed = null;
        speedStatus.textContent = 'Sending motor speed…';
        const result = await post('/api/speed', {value});
        if (nextSpeed === null && Number(speedSlider.value) === value) {
          showSpeed(result.speed);
          speedStatus.textContent = `Applied ${result.speed} / 255 PWM`;
        }
      }
    } catch {
      nextSpeed = null;
      speedStatus.textContent = 'Speed was not applied · check rover connection';
      toast('Could not set motor speed');
    } finally {
      speedBusy = false;
      if (nextSpeed !== null) sendLatestSpeed();
    }
  }
  function queueSpeed(delayMs) {
    showSpeed(Number(speedSlider.value));
    clearTimeout(speedTimer);
    speedTimer = setTimeout(() => {
      nextSpeed = Number(speedSlider.value);
      sendLatestSpeed();
    }, delayMs);
  }
  speedSlider.addEventListener('input', () => queueSpeed(120));
  speedSlider.addEventListener('change', () => queueSpeed(0));
  const driveNote = document.createElement('p');
  driveNote.className = 'note';
  driveNote.textContent = 'Direction correction active here. Release any arrow to stop.';
  speedControl.insertAdjacentElement('afterend', driveNote);
  let wanted = null, held = null, busy = false, timer = null;
  let stopChain = Promise.resolve(), stopAfterCurrent = false, stopCompleted = true;
  function queueStop() {
    stopCompleted = false;
    stopChain = stopChain.then(() => post('/api/drive', {direction:'stop'}))
      .catch(() => {}).finally(() => { stopCompleted = true; });
    return stopChain;
  }
  async function pumpDrive() {
    if (busy || !wanted) return;
    busy = true;
    const direction = wanted;
    try {
      await stopChain;
      if (wanted !== direction) return;
      const started = performance.now();
      await post('/api/drive', {direction});
      const elapsed = Math.round(performance.now() - started);
      driveNote.textContent = `Direction correction active · command response ${elapsed} ms`;
    } catch (error) {
      wanted = null;
      held = null;
      queueStop();
      driveNote.textContent = `Drive request failed: ${error.message} · wheels should stop under the firmware watchdog`;
      toast('Drive request failed; check the message below the controls');
    } finally {
      busy = false;
      if (wanted) timer = setTimeout(pumpDrive, wanted === direction ? 120 : 0);
      else if (stopAfterCurrent) {
        stopAfterCurrent = false;
        if (stopCompleted) queueStop(); // only if stop reached the ESP before the old drive finished
      }
    }
  }
  function stopCorrectedDrive() {
    wanted = null;
    held = null;
    clearTimeout(timer);
    stopAfterCurrent = busy;
    queueStop();  // request stop immediately; server serializes it after an active drive request
  }
  document.querySelectorAll('.dpad [data-dir]').forEach(button => {
    button.onpointerdown = event => {
      event.preventDefault();
      button.setPointerCapture(event.pointerId);
      if (button.dataset.dir === 'stop') { stopCorrectedDrive(); return; }
      held = button;
      wanted = roverDirection[button.dataset.dir];
      stopAfterCurrent = false;
      clearTimeout(timer);
      pumpDrive();
    };
    button.onpointerup = () => { if (held === button) stopCorrectedDrive(); };
    button.onpointercancel = () => { if (held === button) stopCorrectedDrive(); };
    button.onlostpointercapture = () => { if (held === button) stopCorrectedDrive(); };
  });
  window.addEventListener('blur', () => { if (held) stopCorrectedDrive(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden && held) stopCorrectedDrive(); });
  window.PitRoute = {select, draw: drawRoute};
})();
