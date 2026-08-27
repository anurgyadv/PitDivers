const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  live: { state: "disconnected", model_state: "idle", recording: false },
  captures: [],
  runs: [],
  models: [],
  jobs: { active_job: null, jobs: [] },
  sensorHistory: [],
  streamsAttached: false,
  lastCompletedJobs: new Set(),
  filmstrip: { capture: null, count: 0 },
  openChart: null,
  photoSelection: { capture: null, selected: new Set() },
  reconstructFrames: null,
  expandedLogs: new Set(),
  logPopoutJob: null,
  currentDistance: null,
  currentImu: null,
  imuImpactUntil: 0,
  yawZero: null,
  attitudeOverlay: false,
};

const SENSOR_POLL_INTERVAL_MS = 100;  // 10 Hz; matches the HC-SR04 firmware cadence
const MAX_SENSOR_POINTS = 36000;      // ~1 hour of history at 10 Hz
const MIN_WINDOW_MS = 60000;          // axis starts at a 1-minute span
const MAX_WINDOW_MS = 3600000;        // and grows to a 1-hour rolling window
const ENV_COLORS = { temperature: "#ff7433", humidity: "#29d3c2", distance: "#ffc65a" };

const tabMeta = {
  live: ["OPERATIONS", "Live inspection"],
  captures: ["EVIDENCE", "Captured photos"],
  reconstructions: ["SPATIAL OUTPUT", "3D reconstructions"],
  models: ["MODEL LIBRARY", "Depth Anything 3 models"],
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, options = {}) {
  const request = { ...options, headers: { ...(options.headers || {}) } };
  if (request.body && typeof request.body !== "string") {
    request.headers["Content-Type"] = "application/json";
    request.body = JSON.stringify(request.body);
  }
  const response = await fetch(path, request);
  let body = null;
  try { body = await response.json(); } catch { /* no JSON response */ }
  if (!response.ok) {
    throw new Error(body?.detail || body?.error || `Request failed (${response.status})`);
  }
  return body;
}

function toast(title, message = "", kind = "info") {
  const item = document.createElement("div");
  item.className = `toast ${kind}`;
  item.innerHTML = `<strong>${escapeHtml(title)}</strong>${message ? `<span>${escapeHtml(message)}</span>` : ""}`;
  $("#toastStack").append(item);
  setTimeout(() => item.remove(), 4800);
}

function setTab(name) {
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.tab === name));
  $$(".page").forEach((page) => page.classList.toggle("active", page.id === `page-${name}`));
  const [eyebrow, title] = tabMeta[name];
  $("#pageEyebrow").textContent = eyebrow;
  $("#pageTitle").textContent = title;
  if (name === "captures") refreshCaptures();
  if (name === "reconstructions") { refreshRuns(); refreshJobs(); }
  if (name === "models") refreshModels();
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 MB";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}

function formatDate(value) {
  if (!value) return "Unknown date";
  const date = new Date(value);
  return new Intl.DateTimeFormat(undefined, {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

function createCaptureName() {
  const date = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return `live_capture_${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}`;
}

async function refreshHealth() {
  try {
    const health = await api("/api/health");
    $("#systemDot").className = `status-dot ${health.ok ? "online" : "error"}`;
    $("#gpuName").textContent = health.gpu || "GPU unavailable";
    $("#systemStatus").textContent = health.cuda ? "CUDA ready • Local processing" : "CUDA unavailable";
  } catch (error) {
    $("#systemDot").className = "status-dot error";
    $("#gpuName").textContent = "Service unavailable";
    $("#systemStatus").textContent = error.message;
  }
}

function attachStreams() {
  if (state.streamsAttached) return;
  const nonce = Date.now();
  $("#rawStream").src = `/api/live/raw.mjpg?t=${nonce}`;
  $("#depthStream").src = `/api/live/depth.mjpg?t=${nonce}`;
  state.streamsAttached = true;
}

function detachStreams() {
  $("#rawStream").removeAttribute("src");
  $("#depthStream").removeAttribute("src");
  $("#rawFrameWrap").classList.remove("streaming");
  $("#depthFrameWrap").classList.remove("streaming");
  state.streamsAttached = false;
}

function renderLiveStatus() {
  const live = state.live;
  const connected = live.state !== "disconnected";
  const cameraReady = Boolean(live.width && live.height);
  const modelReady = live.model_state === "ready";
  const failed = live.state === "error" || live.model_state === "error";
  const busy = connected && (!cameraReady || !modelReady);

  if (connected) attachStreams(); else detachStreams();
  $("#rawFrameWrap").classList.toggle("streaming", cameraReady);
  $("#depthFrameWrap").classList.toggle("streaming", modelReady && Boolean(live.inference_ms));
  $("#liveNavDot").classList.toggle("on", live.state === "live");

  const dot = $("#liveStatusDot");
  dot.className = `status-dot ${failed ? "error" : busy ? "busy" : live.state === "live" ? "online" : ""}`;
  let title = "Disconnected";
  let detail = "Enter the ESP32 URL to begin";
  if (connected) {
    title = live.state === "reconnecting" ? "Reconnecting camera" : cameraReady ? "Camera connected" : "Connecting camera";
    detail = live.error || (modelReady ? `${live.model_id} ready` : `Loading ${live.model_id || "DA3"}…`);
  }
  if (failed) title = "Attention required";
  $("#liveStatusText").textContent = title;
  $("#liveStatusDetail").textContent = detail;

  const connectButton = $("#connectButton");
  connectButton.textContent = connected ? "Disconnect" : "Connect stream";
  connectButton.classList.toggle("danger", connected);
  connectButton.classList.toggle("primary", !connected);
  $("#streamUrl").disabled = connected;
  $("#liveModel").disabled = connected;
  $("#processRes").disabled = connected;
  $("#inferenceFps").disabled = connected;
  if (connected && Number.isFinite(live.inference_fps)) {
    $("#inferenceFps").value = String(live.inference_fps);
  }

  const recordButton = $("#recordButton");
  recordButton.disabled = !cameraReady;
  recordButton.classList.toggle("active", Boolean(live.recording));
  recordButton.innerHTML = `<span></span>${live.recording ? "Stop recording" : "Start recording"}`;
  $("#captureName").disabled = Boolean(live.recording);
  $("#keyframeFps").disabled = Boolean(live.recording);
  $("#stableOnly").disabled = Boolean(live.recording);

  $("#cameraResolution").textContent = cameraReady ? `${live.width} × ${live.height}` : "No signal";
  $("#cameraFps").textContent = live.capture_fps ? live.capture_fps.toFixed(1) : "—";
  $("#depthFps").textContent = live.depth_fps ? live.depth_fps.toFixed(1) : "—";
  $("#inferenceTime").textContent = live.inference_ms ? `${live.inference_ms} ms` : "—";
  $("#framesSaved").textContent = String(live.frames_saved || 0);
  $("#recordingSession").textContent = live.recording ? live.recording_name : "Not recording";
  $("#depthModelPill").textContent = modelName(live.model_id);
  renderDepthStats(live.depth_stats);
}

function confidenceLabel(score) {
  if (score >= 0.75) return { label: "High", tone: "#5ce09a" };
  if (score >= 0.5) return { label: "Medium", tone: "#ffc65a" };
  return { label: "Low", tone: "#ff5364" };
}

function renderDepthStats(stats) {
  const min = $("#depthMin");
  const avg = $("#depthAvg");
  const max = $("#depthMax");
  const conf = $("#depthConfidence");
  if (!min || !avg || !max || !conf) return;

  if (!stats) {
    for (const el of [min, avg, max, conf]) el.textContent = "—";
    conf.style.color = "";
    return;
  }

  // DA3-Base is not metric, so values are shown in relative units unless a
  // metric model reports true metres via the is_metric flag.
  const unit = stats.metric ? "m" : "rel";
  const digits = stats.metric ? 1 : 2;
  const setDepth = (el, value) =>
    (el.innerHTML = `${Number(value).toFixed(digits)}<span class="stat-unit">${unit}</span>`);
  setDepth(min, stats.min);
  setDepth(avg, stats.avg);
  setDepth(max, stats.max);
  $("#depthLegendTitle").textContent = stats.metric ? "DEPTH (m)" : "RELATIVE DEPTH";

  if (typeof stats.confidence === "number") {
    const level = confidenceLabel(stats.confidence);
    conf.innerHTML = `${level.label}<span class="stat-unit">${Math.round(stats.confidence * 100)}%</span>`;
    conf.style.color = level.tone;
  } else {
    conf.textContent = "—";
    conf.style.color = "";
  }
}

async function refreshLiveStatus(silent = true) {
  try {
    state.live = await api("/api/live/status");
    renderLiveStatus();
  } catch (error) {
    if (!silent) toast("Live status failed", error.message, "error");
  }
}

async function refreshSensors() {
  try {
    const sensor = await api("/api/sensors");
    const dhtValid = sensor.dht_ok !== false && Number.isFinite(sensor.temperature_c) && Number.isFinite(sensor.humidity_percent);
    const sonarValid = sensor.sonar_ok === true && Number.isFinite(sensor.distance_cm);
    const imuValid = sensor.mpu_ok === true
      && [sensor.accel_g?.x, sensor.accel_g?.y, sensor.accel_g?.z, sensor.gyro_dps?.x, sensor.gyro_dps?.y, sensor.gyro_dps?.z, sensor.tilt_deg?.roll, sensor.tilt_deg?.pitch, sensor.tilt_deg?.yaw, sensor.mpu_temperature_c].every(Number.isFinite);
    if (!dhtValid && !sonarValid && !imuValid) {
      throw new Error(sensor.error || "No sensor readings available");
    }
    if (dhtValid) {
      setEnvValue("temperature", sensor.temperature_c, "°C");
      setEnvValue("humidity", sensor.humidity_percent, "%");
    } else {
      setEnvOffline(["temperature", "humidity"]);
    }
    if (sonarValid) {
      state.currentDistance = sensor.distance_cm;
      setEnvValue("distance", sensor.distance_cm, "cm");
    } else {
      state.currentDistance = null;
      setEnvOffline(["distance"], "Out of range");
    }
    if (imuValid) setImuValues(sensor);
    else setImuOffline();
    state.sensorHistory.push({
      time: Date.now(),
      temperature: dhtValid ? sensor.temperature_c : null,
      humidity: dhtValid ? sensor.humidity_percent : null,
      distance: sonarValid ? sensor.distance_cm : null,
      roll: imuValid ? sensor.tilt_deg.roll : null,
      pitch: imuValid ? sensor.tilt_deg.pitch : null,
    });
    if (state.sensorHistory.length > MAX_SENSOR_POINTS) {
      state.sensorHistory.splice(0, state.sensorHistory.length - MAX_SENSOR_POINTS);
    }
    drawSensorCharts();
  } catch (error) {
    state.currentDistance = null;
    setEnvOffline();
    setImuOffline();
    drawSensorCharts();
  }
}

function envStatus(kind, value) {
  if (kind === "distance") {
    return distanceZone(value);
  }
  if (kind === "humidity") {
    if (value < 30) return { label: "Dry", tone: "#ffc65a" };
    if (value <= 60) return { label: "Moderate", tone: "#29d3c2" };
    return { label: "Humid", tone: "#5ce09a" };
  }
  if (value < 10) return { label: "Cold", tone: "#4aa8ff" };
  if (value <= 30) return { label: "Normal", tone: "#5ce09a" };
  return { label: "Hot", tone: "#ff5364" };
}

async function pollSensors() {
  await refreshSensors();
  window.setTimeout(pollSensors, SENSOR_POLL_INTERVAL_MS);
}

function distanceZone(value) {
  if (value < 30) return { label: "STOP", alert: "OBSTACLE VERY CLOSE", message: "Stop distance reached. Proceed with caution.", tone: "#ff5364", start: -90, end: -45, minimum: 0, maximum: 30 };
  if (value < 70) return { label: "CAUTION", alert: "OBSTACLE CLOSE", message: "Obstacle inside the caution zone. Reduce speed.", tone: "#ffc65a", start: -45, end: 0, minimum: 30, maximum: 70 };
  if (value < 150) return { label: "CLEAR", alert: "PATH CLEAR", message: "The immediate path is clear. Continue monitoring.", tone: "#5ce09a", start: 0, end: 45, minimum: 70, maximum: 150 };
  return { label: "SAFE", alert: "SAFE DISTANCE", message: "Long-range clearance detected ahead.", tone: "#30cf72", start: 45, end: 90, minimum: 150, maximum: 400 };
}

function gaugeAngle(value, zone) {
  const clamped = Math.min(Math.max(value, zone.minimum), zone.maximum);
  const progress = (clamped - zone.minimum) / Math.max(1, zone.maximum - zone.minimum);
  return zone.start + progress * (zone.end - zone.start);
}

function updateDistanceGauge(value) {
  const valid = Number.isFinite(value);
  const zone = valid ? distanceZone(value) : null;
  const angle = valid ? gaugeAngle(value, zone) : -90;
  [$("#distanceNeedle"), $("#distanceDetailNeedle")].forEach((needle) => {
    if (needle) needle.setAttribute("transform", `rotate(${angle} 200 190)`);
  });
  [$("#distanceZoneLabel"), $("#distanceDetailZone")].forEach((label) => {
    if (!label) return;
    label.textContent = zone?.label || "WAITING";
    label.style.color = zone?.tone || "var(--muted)";
  });
}

function setEnvValue(kind, value, unit) {
  const valueEl = $(`#${kind}Value`);
  if (valueEl) valueEl.innerHTML = `${value.toFixed(1)}<span class="env-unit">${escapeHtml(unit)}</span>`;
  const status = envStatus(kind, value);
  const pill = $(`#${kind}Status`);
  if (pill) {
    pill.style.color = status.tone;
    pill.style.background = `color-mix(in srgb, ${status.tone} 14%, transparent)`;
    pill.querySelector("em").textContent = status.label;
  }
}

function setEnvOffline(kinds = ["temperature", "humidity", "distance"], label = "Offline") {
  for (const kind of kinds) {
    const valueEl = $(`#${kind}Value`);
    if (valueEl) valueEl.textContent = "—";
    const pill = $(`#${kind}Status`);
    if (pill) {
      pill.style.color = "var(--muted)";
      pill.style.background = "rgba(137,150,163,.12)";
      pill.querySelector("em").textContent = label;
    }
  }
}

async function refreshFilmstrip() {
  const strip = $("#filmstrip");
  const track = $("#filmstripTrack");
  const live = state.live;
  const recordingName = live.recording ? live.recording_name : null;

  if (!recordingName) {
    if (state.filmstrip.capture !== null) {
      state.filmstrip = { capture: null, count: 0 };
      track.innerHTML = "";
    }
    strip.hidden = true;
    return;
  }

  strip.hidden = false;
  if (state.filmstrip.capture !== recordingName) {
    state.filmstrip = { capture: recordingName, count: 0 };
    track.innerHTML = "";
    $("#filmstripCount").textContent = "0 frames";
  }

  const have = state.filmstrip.count;
  if ((live.frames_saved || 0) <= have) return;

  try {
    const page = await api(`/api/captures/${encodeURIComponent(recordingName)}/photos?offset=${have}&limit=500`);
    // Guard against a recording that stopped/switched while we were fetching.
    if (state.filmstrip.capture !== recordingName || !page.photos.length) return;
    const atEnd = track.scrollLeft + track.clientWidth >= track.scrollWidth - 48;
    const fragment = document.createDocumentFragment();
    page.photos.forEach((photo, index) => {
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "filmstrip-cell";
      cell.dataset.photoUrl = photo.url;
      cell.dataset.photoName = photo.name;
      cell.innerHTML = `<img src="${escapeHtml(photo.url)}" alt="${escapeHtml(photo.name)}" loading="lazy" /><span>${have + index + 1}</span>`;
      fragment.append(cell);
    });
    track.append(fragment);
    state.filmstrip.count = have + page.photos.length;
    $("#filmstripCount").textContent = `${state.filmstrip.count} frame${state.filmstrip.count === 1 ? "" : "s"}`;
    // Keep the newest frame in view only if the user hasn't scrolled back.
    if (atEnd) track.scrollLeft = track.scrollWidth;
  } catch { /* transient during recording; next poll retries */ }
}

function chartBounds(values, kind) {
  if (kind === "humidity") {
    const minimum = Math.max(0, Math.floor((Math.min(...values) - 5) / 5) * 5);
    const maximum = Math.min(100, Math.ceil((Math.max(...values) + 5) / 5) * 5);
    return maximum > minimum ? [minimum, maximum] : [Math.max(0, minimum - 5), Math.min(100, maximum + 5)];
  }
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const padding = Math.max(1, (maximum - minimum) * 0.18);
  return [Math.floor((minimum - padding) * 2) / 2, Math.ceil((maximum + padding) * 2) / 2];
}

function formatAgeLabel(ms) {
  const minutes = Math.round(ms / 60000);
  if (minutes <= 1) return "1 MIN AGO";
  if (minutes < 60) return `${minutes} MIN AGO`;
  return "1 HOUR AGO";
}

function drawSensorChart(canvas, { valueKey, color, unit }) {
  if (!canvas) return;
  const bounds = canvas.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;

  const scale = Math.min(window.devicePixelRatio || 1, 2);
  const pixelWidth = Math.round(bounds.width * scale);
  const pixelHeight = Math.round(bounds.height * scale);
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }

  const context = canvas.getContext("2d");
  context.setTransform(scale, 0, 0, scale, 0, 0);
  context.clearRect(0, 0, bounds.width, bounds.height);

  const points = state.sensorHistory.filter((point) => Number.isFinite(point[valueKey]));
  const padding = { left: 12, right: 44, top: 12, bottom: 22 };
  const plotWidth = Math.max(1, bounds.width - padding.left - padding.right);
  const plotHeight = Math.max(1, bounds.height - padding.top - padding.bottom);

  if (points.length < 2) {
    context.font = "10px Inter, ui-sans-serif, system-ui, sans-serif";
    context.fillStyle = "#687580";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(valueKey === "distance" ? "Waiting for HC-SR04 readings…" : "Waiting for DHT11 readings…", padding.left + plotWidth / 2, padding.top + plotHeight / 2);
    return;
  }

  const values = points.map((point) => point[valueKey]);
  const [minimum, maximum] = chartBounds(values, valueKey);
  const range = maximum - minimum || 1;
  const firstTime = points[0].time;
  const lastTime = points.at(-1).time;
  // The axis grows with elapsed time so the line always spans the full width:
  // the newest reading rides the right edge (NOW) and history fills to the
  // left, scrolling once the window reaches its 1-hour cap.
  const displayedWindowMs = Math.min(Math.max(lastTime - firstTime, MIN_WINDOW_MS), MAX_WINDOW_MS);
  const windowStart = lastTime - displayedWindowMs;
  const xFor = (time) => padding.left + ((time - windowStart) / displayedWindowMs) * plotWidth;
  const yFor = (value) => padding.top + ((maximum - value) / range) * plotHeight;

  // Dashed gridlines with right-hand axis labels
  context.font = "10px Inter, ui-sans-serif, system-ui, sans-serif";
  context.textBaseline = "middle";
  context.textAlign = "left";
  for (let index = 0; index <= 3; index += 1) {
    const y = padding.top + (plotHeight * index) / 3;
    context.strokeStyle = "rgba(137, 150, 163, 0.16)";
    context.lineWidth = 1;
    context.setLineDash([4, 5]);
    context.beginPath();
    context.moveTo(padding.left, y);
    context.lineTo(padding.left + plotWidth, y);
    context.stroke();
    context.setLineDash([]);
    const value = maximum - (range * index) / 3;
    context.fillStyle = "#687580";
    context.fillText(`${value.toFixed(valueKey === "humidity" ? 0 : 1)}${unit}`, padding.left + plotWidth + 8, y);
  }

  // Area fill under the line
  const gradient = context.createLinearGradient(0, padding.top, 0, padding.top + plotHeight);
  gradient.addColorStop(0, `${color}33`);
  gradient.addColorStop(1, `${color}00`);
  context.beginPath();
  points.forEach((point, index) => {
    const x = xFor(point.time);
    const y = yFor(point[valueKey]);
    if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
  });
  context.lineTo(xFor(lastTime), padding.top + plotHeight);
  context.lineTo(xFor(firstTime), padding.top + plotHeight);
  context.closePath();
  context.fillStyle = gradient;
  context.fill();

  // Glowing trend line
  context.beginPath();
  points.forEach((point, index) => {
    const x = xFor(point.time);
    const y = yFor(point[valueKey]);
    if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
  });
  context.strokeStyle = color;
  context.lineWidth = 2.4;
  context.lineJoin = "round";
  context.lineCap = "round";
  context.shadowColor = `${color}88`;
  context.shadowBlur = 10;
  context.stroke();
  context.shadowBlur = 0;

  // Bottom time labels
  context.fillStyle = "#56626d";
  context.textBaseline = "alphabetic";
  context.textAlign = "left";
  context.fillText(formatAgeLabel(displayedWindowMs), padding.left, bounds.height - 6);
  context.textAlign = "right";
  context.fillText("NOW", padding.left + plotWidth, bounds.height - 6);

  // End marker: coloured halo with a white centre
  const lastPoint = points.at(-1);
  const endX = xFor(lastPoint.time);
  const endY = yFor(lastPoint[valueKey]);
  context.beginPath();
  context.arc(endX, endY, 6, 0, Math.PI * 2);
  context.fillStyle = `${color}55`;
  context.fill();
  context.beginPath();
  context.arc(endX, endY, 4.5, 0, Math.PI * 2);
  context.fillStyle = color;
  context.fill();
  context.beginPath();
  context.arc(endX, endY, 2.4, 0, Math.PI * 2);
  context.fillStyle = "#ffffff";
  context.fill();
}

function recentDistancePoints(windowMs = 30000, includeInvalid = false) {
  const cutoff = Date.now() - windowMs;
  const recent = state.sensorHistory.filter((point) => point.time >= cutoff);
  return includeInvalid ? recent : recent.filter((point) => Number.isFinite(point.distance));
}

function drawDistanceDetailChart() {
  const canvas = $("#distanceDetailChart");
  if (!canvas || !$("#distanceDialog")?.open) return;
  const bounds = canvas.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;

  const scale = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(bounds.width * scale);
  canvas.height = Math.round(bounds.height * scale);
  const context = canvas.getContext("2d");
  context.setTransform(scale, 0, 0, scale, 0, 0);
  context.clearRect(0, 0, bounds.width, bounds.height);

  const padding = { left: 48, right: 14, top: 14, bottom: 27 };
  const width = Math.max(1, bounds.width - padding.left - padding.right);
  const height = Math.max(1, bounds.height - padding.top - padding.bottom);
  const now = Date.now();
  const start = now - 30000;
  const points = recentDistancePoints();
  const xFor = (time) => padding.left + ((time - start) / 30000) * width;
  const yFor = (value) => padding.top + ((400 - Math.min(Math.max(value, 0), 400)) / 400) * height;

  context.font = "10px Inter, ui-sans-serif, system-ui, sans-serif";
  context.textBaseline = "middle";
  for (const value of [0, 100, 200, 300, 400]) {
    const y = yFor(value);
    context.strokeStyle = "rgba(137,150,163,.13)";
    context.lineWidth = 1;
    context.setLineDash([]);
    context.beginPath(); context.moveTo(padding.left, y); context.lineTo(padding.left + width, y); context.stroke();
    context.fillStyle = "#687580";
    context.textAlign = "right";
    context.fillText(`${value} cm`, padding.left - 7, y);
  }

  for (const threshold of [{ value: 30, label: "STOP", color: "#ff5364" }, { value: 70, label: "CAUTION", color: "#ffc65a" }, { value: 150, label: "CLEAR", color: "#51c449" }]) {
    const y = yFor(threshold.value);
    context.strokeStyle = threshold.color;
    context.globalAlpha = .7;
    context.setLineDash([7, 6]);
    context.beginPath(); context.moveTo(padding.left, y); context.lineTo(padding.left + width, y); context.stroke();
    context.setLineDash([]);
    context.globalAlpha = 1;
    context.fillStyle = threshold.color;
    context.textAlign = "right";
    context.fillText(threshold.label, padding.left + width - 3, y - 8);
  }

  context.fillStyle = "#56626d";
  context.textBaseline = "alphabetic";
  for (let seconds = 30; seconds >= 0; seconds -= 5) {
    const x = padding.left + ((30 - seconds) / 30) * width;
    context.textAlign = seconds === 30 ? "left" : seconds === 0 ? "right" : "center";
    context.fillText(seconds ? `${seconds}s` : "NOW", x, bounds.height - 6);
  }

  if (points.length < 2) {
    context.fillStyle = "#687580";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText("Waiting for distance history…", padding.left + width / 2, padding.top + height / 2);
    return;
  }

  const gradient = context.createLinearGradient(0, padding.top, 0, padding.top + height);
  gradient.addColorStop(0, "rgba(255,198,90,.25)");
  gradient.addColorStop(1, "rgba(255,83,100,.02)");
  context.beginPath();
  points.forEach((point, index) => index ? context.lineTo(xFor(point.time), yFor(point.distance)) : context.moveTo(xFor(point.time), yFor(point.distance)));
  context.lineTo(xFor(points.at(-1).time), padding.top + height);
  context.lineTo(xFor(points[0].time), padding.top + height);
  context.closePath(); context.fillStyle = gradient; context.fill();

  context.beginPath();
  points.forEach((point, index) => index ? context.lineTo(xFor(point.time), yFor(point.distance)) : context.moveTo(xFor(point.time), yFor(point.distance)));
  const currentZone = distanceZone(points.at(-1).distance);
  context.strokeStyle = currentZone.tone;
  context.lineWidth = 3;
  context.lineJoin = "round";
  context.lineCap = "round";
  context.shadowColor = `${currentZone.tone}88`;
  context.shadowBlur = 9;
  context.stroke();
  context.shadowBlur = 0;

  const latest = points.at(-1);
  context.beginPath(); context.arc(xFor(latest.time), yFor(latest.distance), 5, 0, Math.PI * 2);
  context.fillStyle = "#ffffff"; context.fill();
}

function updateDistanceDashboard() {
  const points = recentDistancePoints();
  const value = state.currentDistance;
  updateDistanceGauge(value);

  const detailValue = $("#distanceDetailValue");
  const alert = $("#distanceDetailAlert");
  const message = $("#distanceDetailMessage");
  if (!Number.isFinite(value)) {
    if (detailValue) detailValue.textContent = "—";
    if (alert) {
      alert.style.color = "var(--muted)";
      alert.style.background = "rgba(137,150,163,.1)";
      alert.querySelector("em").textContent = "WAITING FOR SENSOR";
    }
    if (message) message.textContent = "Connect the HC-SR04 to begin monitoring.";
  } else {
    const zone = distanceZone(value);
    if (detailValue) detailValue.innerHTML = `${value.toFixed(1)}<span>cm</span>`;
    if (alert) {
      alert.style.color = zone.tone;
      alert.style.background = `color-mix(in srgb, ${zone.tone} 15%, transparent)`;
      alert.querySelector("em").textContent = zone.alert;
    }
    if (message) message.textContent = zone.message;
  }

  const values = points.map((point) => point.distance);
  const nearest = values.length ? Math.min(...values) : null;
  const average = values.length ? values.reduce((sum, item) => sum + item, 0) / values.length : null;
  $("#distanceNearest").textContent = nearest === null ? "—" : `${nearest.toFixed(1)} cm`;
  $("#distanceAverage").textContent = average === null ? "—" : `${average.toFixed(1)} cm`;

  const ratePoints = recentDistancePoints(10000);
  let rate = null;
  if (ratePoints.length >= 2) {
    const elapsed = (ratePoints.at(-1).time - ratePoints[0].time) / 1000;
    if (elapsed > 0) rate = (ratePoints[0].distance - ratePoints.at(-1).distance) / elapsed;
  }
  const rateEl = $("#distanceApproachRate");
  const rateNote = $("#distanceApproachNote");
  if (rate === null) {
    rateEl.textContent = "—";
    rateEl.style.color = "";
    rateNote.textContent = "Waiting";
  } else if (Math.abs(rate) < .3) {
    rateEl.textContent = "0.0 cm/s";
    rateEl.style.color = "#5ce09a";
    rateNote.textContent = "Holding steady";
  } else if (rate > 0) {
    rateEl.textContent = `↓ ${rate.toFixed(1)} cm/s`;
    rateEl.style.color = "#ff5364";
    rateNote.textContent = "Getting closer";
  } else {
    rateEl.textContent = `↑ ${Math.abs(rate).toFixed(1)} cm/s`;
    rateEl.style.color = "#5ce09a";
    rateNote.textContent = "Moving away";
  }

  const allRecent = recentDistancePoints(30000, true);
  const validRatio = allRecent.length ? points.length / allRecent.length : 0;
  const deltas = points.slice(1).map((point, index) => Math.abs(point.distance - points[index].distance));
  const averageDelta = deltas.length ? deltas.reduce((sum, item) => sum + item, 0) / deltas.length : Infinity;
  const qualityEl = $("#distanceQuality");
  const qualityNote = $("#distanceQualityNote");
  if (!points.length) {
    qualityEl.textContent = "Waiting"; qualityEl.style.color = "var(--muted)"; qualityNote.textContent = "No samples";
  } else if (validRatio >= .8 && averageDelta < 8) {
    qualityEl.textContent = "Stable"; qualityEl.style.color = "#5ce09a"; qualityNote.textContent = "Good echo stability";
  } else if (validRatio >= .6) {
    qualityEl.textContent = "Fair"; qualityEl.style.color = "#ffc65a"; qualityNote.textContent = "Some variation";
  } else {
    qualityEl.textContent = "Weak"; qualityEl.style.color = "#ff5364"; qualityNote.textContent = "Intermittent echoes";
  }
}

function wrapAngle(value) {
  return ((value + 180) % 360 + 360) % 360 - 180;
}

function relativeYaw(rawYaw) {
  if (!Number.isFinite(rawYaw)) return 0;
  if (!Number.isFinite(state.yawZero)) state.yawZero = rawYaw;
  return wrapAngle(rawYaw - state.yawZero);
}

function zeroYaw() {
  if (!state.currentImu) return;
  state.yawZero = state.currentImu.tilt_deg.yaw;
  setImuValues(state.currentImu);
  toast("Yaw zeroed", "The rover's current direction is now 0°.");
}

function updateAttitudeOverlay({ roll, pitch, heading, motionStable, danger }) {
  $("#cameraOverlayWorld").style.transform = `rotate(${-roll.toFixed(2)}deg) translateY(${Math.max(-70, Math.min(70, pitch * 1.45)).toFixed(1)}px)`;
  $("#cameraOverlayRoll").textContent = `${roll.toFixed(1)}°`;
  $("#cameraOverlayPitch").textContent = `${pitch.toFixed(1)}°`;
  $("#cameraOverlayHeading").textContent = `${String(heading).padStart(3, "0")}°`;
  const status = $("#cameraOverlayState");
  status.className = `camera-overlay-state ${danger ? "danger" : motionStable ? "stable" : "moving"}`;
  status.querySelector("span").textContent = danger ? "Attitude warning" : motionStable ? "Stable" : "Moving";
}

function openMotionDetails() {
  const dialog = $("#imuDialog");
  if (!dialog.open) dialog.showModal();
}

function setImuValues(sensor) {
  state.currentImu = sensor;
  const setAxis = (selector, value, digits, unit = "") => {
    const element = $(selector);
    if (element) element.innerHTML = `${value.toFixed(digits)}${unit ? `<small>${unit}</small>` : ""}`;
  };
  const roll = sensor.tilt_deg.roll;
  const pitch = sensor.tilt_deg.pitch;
  const yaw = relativeYaw(sensor.tilt_deg.yaw);
  setAxis("#imuRoll", roll, 1, "°");
  setAxis("#imuPitch", pitch, 1, "°");
  setAxis("#imuYaw", yaw, 1, "°");
  setAxis("#imuSummaryRoll", roll, 1, "°");
  setAxis("#imuSummaryPitch", pitch, 1, "°");
  setAxis("#imuSummaryYaw", yaw, 1, "°");
  setAxis("#imuAccelX", sensor.accel_g.x, 3);
  setAxis("#imuAccelY", sensor.accel_g.y, 3);
  setAxis("#imuAccelZ", sensor.accel_g.z, 3);
  setAxis("#imuGyroX", sensor.gyro_dps.x, 2);
  setAxis("#imuGyroY", sensor.gyro_dps.y, 2);
  setAxis("#imuGyroZ", sensor.gyro_dps.z, 2);
  setAxis("#imuTemperature", sensor.mpu_temperature_c, 1, "°C");
  setAxis("#imuSummaryTemperature", sensor.mpu_temperature_c, 1, "°C");

  const angularRate = Math.hypot(sensor.gyro_dps.x, sensor.gyro_dps.y, sensor.gyro_dps.z);
  const accelerationMagnitude = Math.hypot(sensor.accel_g.x, sensor.accel_g.y, sensor.accel_g.z);
  const shockLoad = Math.abs(accelerationMagnitude - 1);
  setAxis("#imuSummaryAcceleration", accelerationMagnitude, 2, "g");
  setAxis("#imuSummaryRate", angularRate, 1, "°/s");
  const tiltLimit = Number($("#tiltLimit")?.value || 30);
  const maximumTilt = Math.max(Math.abs(roll), Math.abs(pitch));
  const tiltRatio = maximumTilt / tiltLimit;
  const heading = Math.round(((yaw % 360) + 360) % 360) % 360;
  const motionStable = angularRate < 12 && shockLoad < 0.12;
  const now = Date.now();
  if (shockLoad > 0.55 || angularRate > 150) state.imuImpactUntil = now + 1600;
  const impactActive = now < state.imuImpactUntil;
  const captureReady = motionStable && tiltRatio < 1;
  const vibrationPercent = Math.min(100, Math.max(shockLoad / 0.65, angularRate / 160) * 100);
  const direction = Math.abs(roll) >= Math.abs(pitch)
    ? (roll < 0 ? "LEFT LEAN" : "RIGHT LEAN")
    : (pitch < 0 ? "NOSE DOWN" : "NOSE UP");

  $("#imuHorizonWorld").style.transform = `rotate(${-roll.toFixed(2)}deg) translateY(${Math.max(-80, Math.min(80, pitch * 2)).toFixed(1)}px)`;
  $("#imuRover").style.transform = `translate(-50%, -50%) rotate(${Math.max(-12, Math.min(12, roll * .18)).toFixed(2)}deg)`;
  $("#imuHeading").textContent = `${String(heading).padStart(3, "0")}°`;
  $("#tiltLimitValue").textContent = `${tiltLimit.toFixed(0)}°`;
  $("#imuAccelerationMagnitude").textContent = accelerationMagnitude.toFixed(2);
  $("#imuAngularRate").textContent = angularRate.toFixed(1);
  $("#imuVibrationValue").textContent = `${vibrationPercent.toFixed(0)}%`;
  $("#imuVibrationBar").style.width = `${vibrationPercent}%`;

  const safetyBanner = $("#imuSafetyBanner");
  safetyBanner.className = `imu-safety-banner ${tiltRatio >= 1 ? "danger" : tiltRatio >= .75 ? "caution" : "safe"}`;
  $("#imuSafetyStatus").textContent = tiltRatio >= 1 ? "ROLLOVER RISK" : tiltRatio >= .75 ? "EDGE OF ENVELOPE" : "ATTITUDE SAFE";
  $("#imuSafetyNote").textContent = tiltRatio >= 1
    ? `${direction} · reduce tilt immediately`
    : tiltRatio >= .75
      ? `${direction} · ${(tiltLimit - maximumTilt).toFixed(1)}° margin remaining`
      : `Inside the ±${tiltLimit.toFixed(0)}° safety envelope`;
  $("#imuTiltRisk").textContent = `${maximumTilt.toFixed(1)}°`;

  const captureCard = $("#imuCaptureCard");
  captureCard.className = `motion-status-card ${captureReady ? "ready" : "warn"}`;
  $("#imuCaptureState").textContent = captureReady ? "FRAME READY" : "HOLD FRAME";
  $("#imuCaptureNote").textContent = captureReady
    ? "Low motion · keyframe eligible"
    : tiltRatio >= 1 ? "Unsafe rover attitude" : "Movement may blur reconstruction";

  const impactCard = $("#imuImpactCard");
  impactCard.className = `motion-status-card ${impactActive ? "danger" : vibrationPercent > 35 ? "warn" : "ready"}`;
  $("#imuImpactState").textContent = impactActive ? "IMPACT DETECTED" : vibrationPercent > 35 ? "ROUGH TERRAIN" : "NO IMPACT";
  $("#imuImpactNote").textContent = `${shockLoad.toFixed(2)} g dynamic load`;

  const status = $("#imuLive");
  status.style.color = tiltRatio >= 1 || impactActive ? "#ff5364" : !motionStable ? "#ffc65a" : "#5ce09a";
  status.querySelector("em").textContent = tiltRatio >= 1 ? "ROLLOVER RISK" : impactActive ? "IMPACT" : motionStable ? "STABLE" : "MOVING";
  updateAttitudeOverlay({ roll, pitch, heading, motionStable, danger: tiltRatio >= 1 || impactActive });
}

function setImuOffline() {
  state.currentImu = null;
  ["imuRoll", "imuPitch", "imuYaw", "imuAccelX", "imuAccelY", "imuAccelZ", "imuGyroX", "imuGyroY", "imuGyroZ", "imuTemperature"].forEach((id) => {
    const element = $(`#${id}`);
    if (element) element.textContent = "—";
  });
  const status = $("#imuLive");
  if (status) {
    status.style.color = "var(--muted)";
    status.querySelector("em").textContent = "OFFLINE";
  }
  $("#imuHeading").textContent = "—";
  $("#imuAccelerationMagnitude").textContent = "—";
  $("#imuAngularRate").textContent = "—";
  $("#imuVibrationValue").textContent = "—";
  $("#imuVibrationBar").style.width = "0";
  $("#imuHorizonWorld").style.transform = "rotate(0deg) translateY(0)";
  $("#imuRover").style.transform = "translate(-50%, -50%) rotate(0deg)";
  $("#imuSafetyBanner").className = "imu-safety-banner waiting";
  $("#imuSafetyStatus").textContent = "WAITING FOR MPU";
  $("#imuSafetyNote").textContent = "Live rollover protection will appear here";
  $("#imuTiltRisk").textContent = "—";
  $("#imuCaptureCard").className = "motion-status-card";
  $("#imuCaptureState").textContent = "WAITING";
  $("#imuCaptureNote").textContent = "Motion gate unavailable";
  $("#imuImpactCard").className = "motion-status-card";
  $("#imuImpactState").textContent = "WAITING";
  $("#imuImpactNote").textContent = "No motion sample";
  $("#cameraOverlayState").className = "camera-overlay-state";
  $("#cameraOverlayState span").textContent = "MPU waiting";
  ["cameraOverlayRoll", "cameraOverlayPitch", "cameraOverlayHeading", "imuSummaryRoll", "imuSummaryPitch", "imuSummaryYaw", "imuSummaryAcceleration", "imuSummaryRate", "imuSummaryTemperature"].forEach((id) => {
    const element = $(`#${id}`); if (element) element.textContent = "—";
  });
}

const CHART_META = {
  temperature: { valueKey: "temperature", color: "#ff7433", unit: "°", rangeUnit: "°C", label: "Temperature history", cyan: false },
  humidity: { valueKey: "humidity", color: "#29d3c2", unit: "%", rangeUnit: "% RH", label: "Humidity history", cyan: true },
  distance: { valueKey: "distance", color: "#ffc65a", unit: "cm", rangeUnit: "cm", label: "Distance history", cyan: false },
};

function sensorRange(valueKey, rangeUnit) {
  const values = state.sensorHistory.map((point) => point[valueKey]).filter(Number.isFinite);
  if (!values.length) return "Waiting for data";
  return `${Math.min(...values).toFixed(1)}–${Math.max(...values).toFixed(1)} ${rangeUnit}`;
}

function drawSensorCharts() {
  drawSensorChart($("#temperatureSpark"), { valueKey: "temperature", color: ENV_COLORS.temperature, unit: "°" });
  drawSensorChart($("#humiditySpark"), { valueKey: "humidity", color: ENV_COLORS.humidity, unit: "%" });
  updateDistanceDashboard();
  drawDistanceDetailChart();
  if (state.openChart) {
    const meta = state.openChart;
    drawSensorChart($("#chartDialogCanvas"), { valueKey: meta.valueKey, color: meta.color, unit: meta.unit });
    $("#chartDialogRange").textContent = sensorRange(meta.valueKey, meta.rangeUnit);
  }
}

function openDistanceDashboard() {
  const dialog = $("#distanceDialog");
  if (!dialog.open) dialog.showModal();
  updateDistanceDashboard();
  window.requestAnimationFrame(drawDistanceDetailChart);
}

function openChartPopout(kind) {
  const meta = CHART_META[kind];
  if (!meta) return;
  state.openChart = { kind, ...meta };
  $("#chartDialogTitle").textContent = meta.label;
  $("#chartDialogUnit").textContent = meta.rangeUnit;
  $("#chartDialogRange").textContent = sensorRange(meta.valueKey, meta.rangeUnit);
  $(".chart-dialog-canvas").classList.toggle("cyan", Boolean(meta.cyan));
  $("#chartDialog").showModal();
  window.requestAnimationFrame(drawSensorCharts);
}

async function toggleConnection() {
  const button = $("#connectButton");
  button.disabled = true;
  try {
    if (state.live.state !== "disconnected") {
      await api("/api/live/disconnect", { method: "POST" });
      toast("Stream disconnected");
    } else {
      const streamUrl = $("#streamUrl").value.trim();
      if (streamUrl.includes("[") || streamUrl.includes("](") || !/^https?:\/\//i.test(streamUrl)) {
        throw new Error("Use the raw URL, for example http://192.168.0.69:81/stream");
      }
      await api("/api/live/connect", {
        method: "POST",
        body: {
          stream_url: streamUrl,
          model_id: $("#liveModel").value,
          process_res: Number($("#processRes").value),
          inference_fps: Number($("#inferenceFps").value),
        },
      });
      toast("Connecting", "Camera appears first; DA3 depth follows after the model loads.");
    }
    await refreshLiveStatus(false);
  } catch (error) {
    toast("Connection failed", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function toggleRecording() {
  const button = $("#recordButton");
  button.disabled = true;
  try {
    if (state.live.recording) {
      const result = await api("/api/live/record/stop", { method: "POST" });
      toast("Recording saved", `${result.manifest?.frames || 0} keyframes captured.`);
      $("#captureName").value = createCaptureName();
      await refreshCaptures();
    } else {
      const result = await api("/api/live/record/start", {
        method: "POST",
        body: {
          name: $("#captureName").value.trim(),
          keyframe_fps: Number($("#keyframeFps").value),
          stable_only: $("#stableOnly").checked,
        },
      });
      toast("Recording started", $("#stableOnly").checked
        ? `Saving MPU-approved stable frames to data/${result.name}`
        : `Saving keyframes and synchronized telemetry to data/${result.name}`);
    }
    await refreshLiveStatus(false);
  } catch (error) {
    toast("Recording failed", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function modelName(modelId) {
  return state.models.find((model) => model.id === modelId)?.name || modelId?.split("/").pop()?.replaceAll("-", " ") || "DA3";
}

function populateModelSelects() {
  const liveSelect = $("#liveModel");
  const reconstructSelect = $("#reconstructModel");
  const liveValue = liveSelect.value || "depth-anything/DA3-BASE";
  const reconstructValue = reconstructSelect.value || "depth-anything/DA3-BASE";
  const options = state.models.map((model) => {
    const cached = model.cached ? "" : " · download first";
    return `<option value="${escapeHtml(model.id)}" ${model.cached ? "" : "disabled"}>${escapeHtml(model.name + cached)}</option>`;
  }).join("");
  liveSelect.innerHTML = options;
  reconstructSelect.innerHTML = options;
  if ([...liveSelect.options].some((option) => option.value === liveValue && !option.disabled)) liveSelect.value = liveValue;
  else if ([...liveSelect.options].some((option) => option.value === "depth-anything/DA3-BASE" && !option.disabled)) liveSelect.value = "depth-anything/DA3-BASE";
  if ([...reconstructSelect.options].some((option) => option.value === reconstructValue && !option.disabled)) reconstructSelect.value = reconstructValue;
  else reconstructSelect.value = liveSelect.value;
}

async function refreshModels() {
  try {
    state.models = await api("/api/models");
    populateModelSelects();
    renderModels();
  } catch (error) {
    toast("Could not load model list", error.message, "error");
  }
}

function renderModels() {
  const catalog = $("#modelCatalog");
  catalog.innerHTML = state.models.map((model) => {
    const job = model.download;
    const downloading = job?.state === "downloading";
    const error = job?.state === "error";
    const stateClass = model.cached ? "online" : downloading ? "busy" : error ? "error" : "";
    const stateLabel = model.cached ? "Available locally" : downloading ? "Downloading…" : error ? "Download failed" : "Not downloaded";
    return `
      <article class="model-row">
        <div class="model-name"><strong>${escapeHtml(model.name)}</strong><small>${escapeHtml(model.recommended)}</small></div>
        <div class="model-stat"><span>Parameters</span><strong>${escapeHtml(model.parameters)}</strong></div>
        <div class="model-stat"><span>VRAM</span><strong>${escapeHtml(model.vram)}</strong></div>
        <div class="model-stat"><span>Licence</span><strong>${escapeHtml(model.license)}</strong></div>
        <div class="cache-state" title="${escapeHtml(job?.error || "")}"><span class="status-dot ${stateClass}"></span>${escapeHtml(stateLabel)}</div>
        <button class="button ${model.cached ? "secondary" : "primary"}" data-download-model="${escapeHtml(model.id)}" ${model.cached || downloading ? "disabled" : ""}>
          ${model.cached ? "Downloaded" : downloading ? "Downloading" : "Download"}
        </button>
      </article>`;
  }).join("");
}

async function downloadModel(modelId) {
  try {
    await api("/api/models/download", { method: "POST", body: { model_id: modelId } });
    toast("Model download started", modelName(modelId));
    await refreshModels();
  } catch (error) {
    toast("Download failed", error.message, "error");
  }
}

async function refreshCaptures() {
  try {
    state.captures = await api("/api/captures");
    $("#captureBadge").textContent = String(state.captures.length);
    renderCaptures();
  } catch (error) {
    toast("Could not load captures", error.message, "error");
  }
}

function renderCaptures() {
  const grid = $("#captureGrid");
  if (!state.captures.length) {
    grid.innerHTML = `<div class="empty-card"><div><strong>No captures yet</strong>Connect the rover and press Start recording.</div></div>`;
    return;
  }
  grid.innerHTML = state.captures.map((capture) => `
    <article class="asset-card">
      <div class="asset-preview">
        <img src="${escapeHtml(capture.cover_url)}" alt="First frame from ${escapeHtml(capture.name)}" loading="lazy" />
        <span class="asset-type">KEYFRAMES</span>
      </div>
      <div class="asset-body">
        <div class="asset-title-row"><h3>${escapeHtml(capture.name)}</h3><time>${escapeHtml(formatDate(capture.updated_at))}</time></div>
        <div class="asset-meta"><span>${capture.images} photos</span><span>${formatBytes(capture.size_bytes)}</span><span>${capture.manifest?.frame_width ? `${capture.manifest.frame_width}×${capture.manifest.frame_height}` : ""}</span></div>
        <div class="asset-actions">
          <button class="button secondary" data-open-photos="${escapeHtml(capture.name)}">View photos</button>
          <button class="button primary" data-reconstruct="${escapeHtml(capture.name)}">Build 3D</button>
        </div>
      </div>
    </article>`).join("");
}

async function openPhotos(captureName) {
  const dialog = $("#photoDialog");
  $("#photoDialogTitle").textContent = captureName;
  $("#photoGrid").innerHTML = `<div class="empty-card"><div>Loading photos…</div></div>`;
  state.photoSelection = { capture: captureName, selected: new Set() };
  updatePhotoSelection();
  dialog.showModal();
  try {
    let offset = 0;
    let total = 1;
    const photos = [];
    while (offset < total) {
      const page = await api(`/api/captures/${encodeURIComponent(captureName)}/photos?offset=${offset}&limit=500`);
      total = page.total;
      photos.push(...page.photos);
      offset += page.photos.length;
      if (!page.photos.length) break;
    }
    $("#photoSummary").textContent = `${photos.length} photos • tick frames for reconstruction, or open one full size`;
    $("#photoTotalCount").textContent = String(photos.length);
    $("#photoGrid").innerHTML = photos.map((photo) => `
      <button class="photo-cell" type="button" data-frame="${escapeHtml(photo.name)}" aria-pressed="false" title="${escapeHtml(photo.name)}">
        <img src="${escapeHtml(photo.url)}" alt="${escapeHtml(photo.name)}" loading="lazy" />
        <span class="photo-check">✓</span>
        <span class="photo-zoom" data-photo-url="${escapeHtml(photo.url)}" data-photo-name="${escapeHtml(photo.name)}" title="Open full size">⛶</span>
      </button>`).join("");
    updatePhotoSelection();
  } catch (error) {
    $("#photoGrid").innerHTML = `<div class="empty-card"><div><strong>Could not load photos</strong>${escapeHtml(error.message)}</div></div>`;
  }
}

function togglePhotoFrame(name) {
  const selected = state.photoSelection.selected;
  if (selected.has(name)) selected.delete(name); else selected.add(name);
  const cell = $(`.photo-cell[data-frame="${CSS.escape(name)}"]`);
  if (cell) {
    const on = selected.has(name);
    cell.classList.toggle("selected", on);
    cell.setAttribute("aria-pressed", on ? "true" : "false");
  }
  updatePhotoSelection();
}

function setPhotoSelectionAll(select) {
  const selected = state.photoSelection.selected;
  selected.clear();
  if (select) {
    for (const cell of $$(".photo-cell")) selected.add(cell.dataset.frame);
  }
  for (const cell of $$(".photo-cell")) {
    const on = selected.has(cell.dataset.frame);
    cell.classList.toggle("selected", on);
    cell.setAttribute("aria-pressed", on ? "true" : "false");
  }
  updatePhotoSelection();
}

function updatePhotoSelection() {
  const count = state.photoSelection.selected.size;
  $("#photoSelectedCount").textContent = String(count);
  const build = $("#photoBuildSelected");
  build.disabled = count < 2;
  build.textContent = count > 0 ? `Build 3D from ${count} frame${count === 1 ? "" : "s"}` : "Build 3D from selected";
}

function openReconstruct(captureName, frames = null) {
  const capture = state.captures.find((item) => item.name === captureName);
  state.reconstructFrames = frames && frames.length ? frames : null;
  $("#reconstructCapture").value = captureName;
  const total = capture?.images || 0;
  const scope = state.reconstructFrames
    ? `${state.reconstructFrames.length} of ${total} frames selected`
    : `${total} keyframes • ${formatBytes(capture?.size_bytes || 0)}`;
  $("#reconstructTarget").innerHTML = `<strong>${escapeHtml(captureName)}</strong><br>${escapeHtml(scope)}`;
  $("#reconstructDialog").showModal();
}

async function submitReconstruction(event) {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    if (state.live.state !== "disconnected") {
      await api("/api/live/disconnect", { method: "POST" });
      await refreshLiveStatus();
    }
    const job = await api("/api/jobs/reconstruct", {
      method: "POST",
      body: {
        capture_name: $("#reconstructCapture").value,
        model_id: $("#reconstructModel").value,
        process_res: Number($("#reconstructRes").value),
        conf_thresh_percentile: Number($("#reconstructConf").value),
        num_max_points: Number($("#reconstructPoints").value),
        show_cameras: $("#reconstructCameras").value === "true",
        frames: state.reconstructFrames,
      },
    });
    state.reconstructFrames = null;
    $("#reconstructDialog").close();
    setTab("reconstructions");
    toast("Reconstruction started", `${job.images} images with ${modelName(job.model_id)}`);
    await refreshJobs();
  } catch (error) {
    toast("Could not start reconstruction", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function refreshJobs() {
  try {
    const previous = new Set(state.jobs.jobs.filter((job) => job.state === "complete").map((job) => job.id));
    state.jobs = await api("/api/jobs");
    for (const job of state.jobs.jobs) {
      if (job.state === "complete" && !previous.has(job.id) && !state.lastCompletedJobs.has(job.id)) {
        state.lastCompletedJobs.add(job.id);
        toast("3D reconstruction complete", `${job.run_name}/scene.glb is ready.`);
        refreshRuns();
      }
    }
    renderJobs();
    renderLogPopout();
  } catch { /* polling will retry */ }
}

function renderJobs() {
  const container = $("#activeJobs");
  const shown = state.jobs.jobs.filter((job) =>
    ["queued", "running", "cancelling", "error", "cancelled"].includes(job.state));
  container.innerHTML = shown.map((job) => {
    const terminal = ["error", "cancelled"].includes(job.state);
    const expanded = state.expandedLogs.has(job.id);
    const hasLogs = Boolean(job.logs?.length);
    const scope = job.selected_frames ? `${job.selected_frames} selected frames` : `${job.images} images`;
    return `
    <article class="job-card">
      <div class="job-top">
        <div><p class="eyebrow">${escapeHtml(job.state.toUpperCase())}</p><h3>${escapeHtml(job.capture)} → ${escapeHtml(job.run_name)}</h3><p>${escapeHtml(job.stage)} • ${escapeHtml(scope)} • ${escapeHtml(modelName(job.model_id))}</p></div>
        ${["queued", "running"].includes(job.state) ? `<button class="button danger" data-cancel-job="${escapeHtml(job.id)}">Stop</button>` : ""}
      </div>
      <div class="progress-track"><span style="width:${Number(job.progress || 0)}%"></span></div>
      <div class="job-foot"><span>${escapeHtml(job.error || job.stage)}</span><strong>${Number(job.progress || 0)}%</strong></div>
      <div class="job-actions">
        ${hasLogs ? `<button class="button secondary" data-toggle-logs="${escapeHtml(job.id)}">${expanded ? "Hide" : "Show"} terminal</button>` : ""}
        ${hasLogs ? `<button class="button secondary" data-pop-logs="${escapeHtml(job.id)}">Pop out</button>` : ""}
        ${terminal ? `<button class="button danger" data-dismiss-job="${escapeHtml(job.id)}">Dismiss</button>` : ""}
      </div>
      ${hasLogs ? `<pre class="job-logs${expanded ? "" : " collapsed"}">${escapeHtml(job.logs.slice(-14).join("\n"))}</pre>` : ""}
    </article>`;
  }).join("");
}

function toggleLogs(jobId) {
  if (state.expandedLogs.has(jobId)) state.expandedLogs.delete(jobId);
  else state.expandedLogs.add(jobId);
  renderJobs();
}

function openLogPopout(jobId) {
  state.logPopoutJob = jobId;
  const job = state.jobs.jobs.find((item) => item.id === jobId);
  $("#logDialogTitle").textContent = job ? `${job.capture} → ${job.run_name}` : "Reconstruction log";
  renderLogPopout();
  $("#logDialog").showModal();
}

function renderLogPopout() {
  if (!state.logPopoutJob) return;
  const body = $("#logDialogBody");
  if (!body) return;
  const job = state.jobs.jobs.find((item) => item.id === state.logPopoutJob);
  const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
  body.textContent = job?.logs?.length ? job.logs.join("\n") : "No output yet.";
  if (nearBottom) body.scrollTop = body.scrollHeight;
}

async function cancelJob(jobId) {
  try {
    await api(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
    toast("Stopping reconstruction", "The DA3 process is being terminated.");
    await refreshJobs();
  } catch (error) {
    toast("Could not stop job", error.message, "error");
  }
}

async function dismissJob(jobId) {
  try {
    await api(`/api/jobs/${encodeURIComponent(jobId)}/dismiss`, { method: "POST" });
    state.expandedLogs.delete(jobId);
    if (state.logPopoutJob === jobId) { state.logPopoutJob = null; $("#logDialog").close(); }
    await refreshJobs();
  } catch (error) {
    toast("Could not dismiss job", error.message, "error");
  }
}

async function refreshRuns() {
  try {
    state.runs = await api("/api/runs");
    $("#runBadge").textContent = String(state.runs.length);
    renderRuns();
  } catch (error) {
    toast("Could not load 3D models", error.message, "error");
  }
}

function renderRuns() {
  const grid = $("#runGrid");
  if (!state.runs.length) {
    grid.innerHTML = `<div class="empty-card"><div><strong>No 3D models yet</strong>Choose a capture and run DA3 reconstruction.</div></div>`;
    return;
  }
  grid.innerHTML = state.runs.map((run) => `
    <article class="asset-card">
      <div class="asset-preview">
        ${run.thumbnail_url ? `<img src="${escapeHtml(run.thumbnail_url)}" alt="Depth preview for ${escapeHtml(run.name)}" loading="lazy" />` : `<div class="preview-placeholder">◇</div>`}
        <span class="asset-type">GLB SCENE</span>
      </div>
      <div class="asset-body">
        <div class="asset-title-row"><h3>${escapeHtml(run.name)}</h3><time>${escapeHtml(formatDate(run.updated_at))}</time></div>
        <div class="asset-meta"><span>${formatBytes(run.size_bytes)}</span><span>Interactive point cloud</span></div>
        <div class="asset-actions">
          <button class="button primary" data-view-run="${escapeHtml(run.name)}">Open 3D viewer</button>
          <button class="button secondary" data-rename-run="${escapeHtml(run.name)}">Rename</button>
          <a class="button secondary" href="${escapeHtml(run.download_url)}">Download</a>
        </div>
      </div>
    </article>`).join("");
}

async function renameRun(runName) {
  const next = window.prompt("Rename reconstruction", runName);
  if (next == null) return;
  const trimmed = next.trim();
  if (!trimmed || trimmed === runName) return;
  try {
    const result = await api(`/api/runs/${encodeURIComponent(runName)}/rename`, {
      method: "POST",
      body: { new_name: trimmed },
    });
    toast("Reconstruction renamed", `Now “${result.name}”.`);
    await refreshRuns();
  } catch (error) {
    toast("Could not rename", error.message, "error");
  }
}

function openViewer(runName) {
  const run = state.runs.find((item) => item.name === runName);
  if (!run) return;
  $("#viewerTitle").textContent = runName;
  $("#sceneViewer").src = `${run.model_url}?t=${Date.now()}`;
  $("#downloadGlb").href = run.download_url;
  $("#viewerDialog").showModal();
}

function closeDialog(dialog) {
  if (dialog.id === "viewerDialog") $("#sceneViewer").removeAttribute("src");
  if (dialog.id === "chartDialog") state.openChart = null;
  if (dialog.id === "logDialog") state.logPopoutJob = null;
  dialog.close();
}

function bindEvents() {
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => setTab(button.dataset.tab)));
  $("#connectButton").addEventListener("click", toggleConnection);
  $("#recordButton").addEventListener("click", toggleRecording);
  $("#tiltLimit").addEventListener("input", () => {
    $("#tiltLimitValue").textContent = `${Number($("#tiltLimit").value).toFixed(0)}°`;
    if (state.currentImu) setImuValues(state.currentImu);
  });
  $("#zeroYawButton").addEventListener("click", zeroYaw);
  $("#openImuDialog").addEventListener("click", openMotionDetails);
  $("#cameraOverlayToggle").addEventListener("click", () => {
    state.attitudeOverlay = !state.attitudeOverlay;
    const button = $("#cameraOverlayToggle");
    const overlay = $("#cameraAttitudeOverlay");
    button.setAttribute("aria-pressed", String(state.attitudeOverlay));
    button.textContent = state.attitudeOverlay ? "Overlay on" : "Attitude overlay";
    overlay.hidden = !state.attitudeOverlay;
    overlay.setAttribute("aria-hidden", String(!state.attitudeOverlay));
  });
  $("#refreshButton").addEventListener("click", refreshAll);
  $("#reconstructForm").addEventListener("submit", submitReconstruction);
  $$('[data-go-live]').forEach((button) => button.addEventListener("click", () => setTab("live")));
  $$('[data-go-captures]').forEach((button) => button.addEventListener("click", () => setTab("captures")));

  $("#photoSelectAll").addEventListener("click", () => setPhotoSelectionAll(true));
  $("#photoSelectNone").addEventListener("click", () => setPhotoSelectionAll(false));
  $("#photoBuildSelected").addEventListener("click", () => {
    const frames = [...state.photoSelection.selected];
    const capture = state.photoSelection.capture;
    if (!capture || frames.length < 2) return;
    closeDialog($("#photoDialog"));
    openReconstruct(capture, frames);
  });

  document.addEventListener("click", (event) => {
    const photoButton = event.target.closest("[data-open-photos]");
    const reconstructButton = event.target.closest("[data-reconstruct]");
    const viewerButton = event.target.closest("[data-view-run]");
    const downloadButton = event.target.closest("[data-download-model]");
    const cancelButton = event.target.closest("[data-cancel-job]");
    const dismissButton = event.target.closest("[data-dismiss-job]");
    const toggleLogsButton = event.target.closest("[data-toggle-logs]");
    const popLogsButton = event.target.closest("[data-pop-logs]");
    const renameButton = event.target.closest("[data-rename-run]");
    const popChartButton = event.target.closest("[data-pop-chart]");
    const zoomButton = event.target.closest("[data-photo-url]");
    const photoCell = event.target.closest("[data-frame]");
    const distanceCard = event.target.closest("[data-open-distance]");
    if (photoButton) openPhotos(photoButton.dataset.openPhotos);
    if (reconstructButton) openReconstruct(reconstructButton.dataset.reconstruct);
    if (viewerButton) openViewer(viewerButton.dataset.viewRun);
    if (downloadButton) downloadModel(downloadButton.dataset.downloadModel);
    if (cancelButton) cancelJob(cancelButton.dataset.cancelJob);
    if (dismissButton) dismissJob(dismissButton.dataset.dismissJob);
    if (toggleLogsButton) toggleLogs(toggleLogsButton.dataset.toggleLogs);
    if (popLogsButton) openLogPopout(popLogsButton.dataset.popLogs);
    if (renameButton) renameRun(renameButton.dataset.renameRun);
    if (popChartButton) openChartPopout(popChartButton.dataset.popChart);
    if (distanceCard) openDistanceDashboard();
    if (zoomButton) {
      $("#lightboxImage").src = zoomButton.dataset.photoUrl;
      $("#lightboxLabel").textContent = zoomButton.dataset.photoName;
      $("#lightbox").hidden = false;
    } else if (photoCell) {
      togglePhotoFrame(photoCell.dataset.frame);
    }
  });

  $("[data-open-distance]").addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openDistanceDashboard();
    }
  });

  $$(".modal-close").forEach((button) => button.addEventListener("click", () => closeDialog(button.closest("dialog"))));
  $$("dialog").forEach((dialog) => dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeDialog(dialog);
  }));
  $("#lightboxClose").addEventListener("click", () => { $("#lightbox").hidden = true; });
  $("#lightbox").addEventListener("click", (event) => {
    if (event.target === $("#lightbox")) $("#lightbox").hidden = true;
  });
  $("#fullscreenViewer").addEventListener("click", async () => {
    try {
      if (!document.fullscreenElement) await $("#viewerDialog").requestFullscreen();
      else await document.exitFullscreen();
    } catch (error) { toast("Fullscreen unavailable", error.message, "error"); }
  });
  $("#rawStream").addEventListener("load", () => $("#rawFrameWrap").classList.add("streaming"));
  $("#depthStream").addEventListener("load", () => $("#depthFrameWrap").classList.add("streaming"));
}

async function refreshAll() {
  await Promise.allSettled([
    refreshHealth(), refreshModels(), refreshLiveStatus(false), refreshSensors(), refreshCaptures(), refreshRuns(), refreshJobs(),
  ]);
}

function updateClock() {
  $("#clock").textContent = new Intl.DateTimeFormat(undefined, {
    weekday: "short", hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).format(new Date());
}

async function initialize() {
  const imuPanel = $(".env-grid > .imu-card");
  const imuDialogBody = $("#imuDialogBody");
  if (imuPanel && imuDialogBody) imuDialogBody.append(imuPanel);
  bindEvents();
  $("#captureName").value = createCaptureName();
  updateClock();
  setInterval(updateClock, 1000);
  window.addEventListener("resize", () => window.requestAnimationFrame(drawSensorCharts));
  drawSensorCharts();
  await refreshAll();
  setInterval(() => refreshLiveStatus(), 1000);
  window.setTimeout(pollSensors, SENSOR_POLL_INTERVAL_MS);
  setInterval(() => refreshFilmstrip(), 800);
  setInterval(() => refreshJobs(), 1200);
  setInterval(() => { refreshCaptures(); refreshRuns(); refreshModels(); }, 6000);
}

initialize();
