const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  live: { state: "disconnected", model_state: "idle", recording: false },
  captures: [],
  runs: [],
  reports: [],
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
  semanticObjects: [],
  semanticRegistry: null,
  semanticRun: null,
  semanticSelected: null,
  semanticFilter: "all",
  rover: { connected: false, status: null, activeCommand: null, repeatTimer: null, requestPending: false },
  gamepad: { running: false },
  autonomy: { state: "idle", running: false },
};

const SENSOR_POLL_INTERVAL_MS = 100;  // 10 Hz; matches the HC-SR04 firmware cadence
const MAX_SENSOR_POINTS = 36000;      // ~1 hour of history at 10 Hz
const MIN_WINDOW_MS = 60000;          // axis starts at a 1-minute span
const MAX_WINDOW_MS = 3600000;        // and grows to a 1-hour rolling window
const ENV_COLORS = { temperature: "#ff7433", humidity: "#29d3c2", distance: "#ffc65a" };

const tabMeta = {
  live: ["OPERATIONS", "Live inspection"],
  expedition: ["FIELD SESSION", "Rover expedition"],
  setup: ["DEVICE NETWORK", "Setup"],
  control: ["REMOTE OPERATIONS", "Drive rover"],
  captures: ["EVIDENCE", "Captured photos"],
  reports: ["INSPECTION", "Mining reports"],
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
    throw new Error(formatApiError(body?.detail ?? body?.error, response.status));
  }
  return body;
}

function formatApiError(detail, status) {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (typeof item === "string") return item;
      const location = Array.isArray(item?.loc) ? item.loc.filter((part) => part !== "body").join(".") : "";
      const message = item?.msg || item?.message || item?.error;
      return message ? `${location ? `${location}: ` : ""}${message}` : JSON.stringify(item);
    }).filter(Boolean);
    if (messages.length) return messages.join(" · ");
  }
  if (detail && typeof detail === "object") {
    const nested = detail.message ?? detail.error ?? detail.detail ?? detail.msg;
    if (nested !== undefined) return formatApiError(nested, status);
    try { return JSON.stringify(detail); } catch { /* use fallback below */ }
  }
  return `Request failed (${status})`;
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
  if (name === "reports") { refreshInspectionReports(); refreshExpeditionMap(); }
  if (name === "expedition") refreshExpeditionMap();
  if (name === "control") updateDriveStream(true);
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

function attachStreams(depthEnabled = true, semanticEnabled = false) {
  if (!state.streamsAttached) {
    $("#rawStream").src = `/api/live/raw.mjpg?t=${Date.now()}`;
  }
  if (depthEnabled) {
    if (!$("#depthStream").getAttribute("src")) {
      $("#depthStream").src = `/api/live/depth.mjpg?t=${Date.now()}`;
    }
  } else {
    $("#depthStream").removeAttribute("src");
    $("#depthFrameWrap").classList.remove("streaming");
  }
  if (semanticEnabled) {
    if (!$("#semanticStream").getAttribute("src")) {
      $("#semanticStream").src = `/api/live/semantic.mjpg?t=${Date.now()}`;
    }
  } else {
    $("#semanticStream").removeAttribute("src");
    $("#semanticFrameWrap").classList.remove("streaming");
  }
  state.streamsAttached = true;
  applyFeedVisibility();
}

function applyFeedVisibility(save = false) {
  const visibility = {
    raw: Boolean($("#showRawFeed")?.checked),
    depth: Boolean($("#showDepthFeed")?.checked),
    semantic: Boolean($("#showSemanticFeed")?.checked),
  };
  $("#rawStreamCard").hidden = !visibility.raw;
  $("#depthStreamCard").hidden = !visibility.depth;
  $("#semanticStreamCard").hidden = !visibility.semantic;
  if (save) localStorage.setItem("pitdivers.feedVisibility", JSON.stringify(visibility));
}

function detachStreams() {
  $("#rawStream").removeAttribute("src");
  $("#depthStream").removeAttribute("src");
  $("#semanticStream").removeAttribute("src");
  $("#rawFrameWrap").classList.remove("streaming");
  $("#depthFrameWrap").classList.remove("streaming");
  $("#semanticFrameWrap").classList.remove("streaming");
  $("#driveCamera").removeAttribute("src");
  $("#driveCameraWrap").classList.remove("streaming");
  state.streamsAttached = false;
}

function updateDriveStream(force = false) {
  const live = state.live;
  const cameraReady = Boolean(live.width && live.height);
  const wantsOriginal = $("#driveViewSource")?.value === "original";
  const wantsDetection = Boolean($("#driveDetection")?.checked);
  const detectionReady = wantsDetection && live.semantic_enabled === true && live.semantic_state === "ready";
  const path = wantsOriginal
    ? "/api/live/original.mjpg"
    : detectionReady
      ? "/api/live/semantic.mjpg"
      : "/api/live/raw.mjpg";
  const camera = $("#driveCamera");
  if (live.state === "disconnected") {
    camera?.removeAttribute("src");
  } else if (camera && (force || !camera.src.includes(path))) {
    camera.src = `${path}?drive=${Date.now()}`;
  }
  $("#driveCameraWrap")?.classList.toggle("streaming", cameraReady);
  $("#driveNavDot")?.classList.toggle("on", live.state === "live" && state.rover.connected);
  const badge = $("#driveVisionState");
  if (!badge) return;
  badge.textContent = !cameraReady
    ? "Camera offline"
    : wantsOriginal
      ? "Original feed"
      : detectionReady
        ? "Detection on"
        : wantsDetection
          ? "Detection unavailable"
          : "Detection off";
  badge.classList.toggle("accent", detectionReady);
}

function renderLiveStatus() {
  const live = state.live;
  const connected = live.state !== "disconnected";
  const depthEnabled = connected
    ? live.depth_enabled !== false
    : Boolean($("#liveModel")?.value);
  const semanticEnabled = connected
    ? live.semantic_enabled === true
    : $("#semanticEnabled")?.value === "true";
  const cameraReady = Boolean(live.width && live.height);
  const modelReady = !depthEnabled || live.model_state === "ready";
  const failed = live.state === "error" || (depthEnabled && live.model_state === "error");
  const busy = connected && (!cameraReady || !modelReady);

  if (connected) attachStreams(depthEnabled, semanticEnabled); else detachStreams();
  $("#rawFrameWrap").classList.toggle("streaming", cameraReady);
  $("#depthFrameWrap").classList.toggle("streaming", depthEnabled && modelReady && Boolean(live.inference_ms));
  $("#semanticFrameWrap").classList.toggle("streaming", semanticEnabled && live.semantic_state === "ready" && Boolean(live.semantic_fps));
  $("#liveNavDot").classList.toggle("on", live.state === "live");

  const dot = $("#liveStatusDot");
  dot.className = `status-dot ${failed ? "error" : busy ? "busy" : live.state === "live" ? "online" : ""}`;
  let title = "Disconnected";
  let detail = "Enter the ESP32 URL to begin";
  if (connected) {
    title = live.state === "reconnecting" ? "Reconnecting camera" : cameraReady ? "Camera connected" : "Connecting camera";
    detail = live.error || live.camera_profile_error || (!depthEnabled ? "Camera-only mode · depth processing off" : modelReady ? `${live.model_id} ready` : `Loading ${live.model_id || "DA3"}…`);
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
  $("#semanticEnabled").disabled = connected;
  $("#cameraProfile").disabled = connected;
  $("#processRes").disabled = connected || !depthEnabled;
  $("#inferenceFps").disabled = connected || !depthEnabled;
  $("#semanticFps").disabled = connected || !semanticEnabled;
  if (connected && Number.isFinite(live.inference_fps)) {
    $("#inferenceFps").value = String(live.inference_fps);
  }

  const recordButton = $("#recordButton");
  recordButton.disabled = !cameraReady;
  recordButton.classList.toggle("active", Boolean(live.recording));
  recordButton.innerHTML = `<span></span>${live.recording ? "Stop recording" : "Start recording"}`;
  const inspectionCamera = $("#inspectionCamera");
  if (cameraReady && !inspectionCamera.src.endsWith("/api/live/raw.mjpg")) inspectionCamera.src = "/api/live/raw.mjpg";
  if (!cameraReady && inspectionCamera.getAttribute("src")) inspectionCamera.removeAttribute("src");
  inspectionCamera.hidden = !cameraReady;
  $("#expeditionCameraState").textContent = cameraReady ? (live.recording ? "Recording" : "Live") : "Offline";
  $("#expeditionCameraEmpty").hidden = cameraReady;
  if (cameraReady && !$("#expeditionCamera").src.endsWith("/api/live/raw.mjpg")) $("#expeditionCamera").src = "/api/live/raw.mjpg";
  if (!cameraReady) $("#expeditionCamera").removeAttribute("src");
  $("#inspectionCameraPlaceholder").hidden = cameraReady;
  $("#inspectionCameraStatus").textContent = cameraReady ? "Camera live" : "Camera disconnected";
  $("#inspectionCaptureStatus").textContent = live.recording ? `Recording ${live.recording_name} · ${live.frames_saved || 0} keyframes` : "Not recording";
  $("#inspectionRecordButton").disabled = !cameraReady;
  $("#inspectionRecordButton").textContent = live.recording ? "Stop recording" : "Start recording";
  $("#captureName").disabled = Boolean(live.recording);
  $("#keyframeFps").disabled = Boolean(live.recording);
  $("#stableOnly").disabled = Boolean(live.recording);

  $("#cameraResolution").textContent = cameraReady ? `${live.width} × ${live.height}` : "No signal";
  $("#cameraFps").textContent = live.capture_fps ? live.capture_fps.toFixed(1) : "—";
  $("#depthFps").textContent = !depthEnabled ? "Off" : live.depth_fps ? live.depth_fps.toFixed(1) : "—";
  $("#inferenceTime").textContent = !depthEnabled ? "Off" : live.inference_ms ? `${live.inference_ms} ms` : "—";
  $("#framesSaved").textContent = String(live.frames_saved || 0);
  $("#recordingSession").textContent = live.recording ? live.recording_name : "Not recording";
  $("#depthModelPill").textContent = depthEnabled ? modelName(live.model_id) : "OFF";
  $("#semanticModelPill").textContent = !semanticEnabled ? "OFF" : live.semantic_state === "error" ? "ERROR" : live.semantic_state === "ready" ? "YOLOE · READY" : "LOADING";
  $("#semanticEmptyTitle").textContent = !semanticEnabled ? "Semantic disabled" : live.semantic_state === "error" ? "Semantic error" : "Semantic idle";
  $("#semanticEmptyDetail").textContent = live.semantic_error || (!semanticEnabled ? "Enable live semantics before connecting" : "YOLOE loads after the stream connects");
  $("#semanticObjectsCount").textContent = semanticEnabled && Array.isArray(live.semantic_objects) ? String(live.semantic_objects.length) : "—";
  $("#semanticPoseState").textContent = live.semantic_pose_state === "view-local" ? "View-local · pose pending" : "World anchored";
  $("#depthEmptyTitle").textContent = depthEnabled ? "Depth idle" : "Depth disabled";
  $("#depthEmptyDetail").textContent = depthEnabled ? "The model loads after the stream connects" : "Camera and sensor recording continue without GPU inference";
  renderDepthStats(live.depth_stats);
  const enhancement = connected
    ? (live.low_light || { mode: "off", strength: 55, model_state: "idle" })
    : { mode: $("#lowLightMode")?.value || "fast", strength: Number($("#lowLightStrength")?.value || 55), model_state: $("#lowLightMode")?.value === "off" ? "idle" : "ready" };
  if (connected && $("#lowLightMode") && document.activeElement !== $("#lowLightMode")) $("#lowLightMode").value = enhancement.mode;
  if (connected && $("#lowLightStrength") && document.activeElement !== $("#lowLightStrength")) $("#lowLightStrength").value = String(enhancement.strength);
  if ($("#lowLightStrengthValue")) $("#lowLightStrengthValue").textContent = `${enhancement.strength}%`;
  renderEnhancementStatus(enhancement);
  updateDriveStream();
  updateRecordingTimer();
}

function renderEnhancementStatus(enhancement) {
  const mode = enhancement.mode || "off";
  const failed = enhancement.model_state === "error";
  const busy = enhancement.model_state === "loading";
  const dot = $("#enhancementStatusDot");
  if (!dot) return;
  dot.className = `status-dot ${failed ? "error" : busy ? "busy" : mode === "off" ? "" : "online"}`;
  $("#enhancementStatus").textContent = failed ? "Enhancement fallback" : mode === "ai" ? "SCUNet neural denoise" : mode === "fast" ? "Fast enhancement" : "Original image";
  $("#enhancementDetail").textContent = enhancement.error || (mode === "ai"
    ? `${enhancement.processing_ms || 0} ms · ${(enhancement.provider || "cpu").toUpperCase()} neural denoise + adaptive illumination`
    : mode === "fast"
      ? `${enhancement.processing_ms || 0} ms · temporal denoise + adaptive illumination`
      : "No processing applied");
}

let enhancementTimer = null;
function applyLowLightSettings(immediate = false) {
  window.clearTimeout(enhancementTimer);
  const apply = async () => {
    const mode = $("#lowLightMode").value;
    const strength = Number($("#lowLightStrength").value);
    localStorage.setItem("pitdivers.lowLightMode", mode);
    localStorage.setItem("pitdivers.lowLightStrength", String(strength));
    $("#lowLightStrengthValue").textContent = `${strength}%`;
    try {
      const enhancement = await api("/api/live/enhancement", { method: "POST", body: { mode, strength } });
      state.live.low_light = enhancement;
      renderEnhancementStatus(enhancement);
      if ($("#driveViewSource").value === "enhanced") updateDriveStream(true);
    } catch (error) {
      toast("Enhancement update failed", error.message, "error");
    }
  };
  if (immediate) apply(); else enhancementTimer = window.setTimeout(apply, 180);
}

function formatRecordingDuration(totalSeconds) {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  const clock = `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
  return hours ? `${String(hours).padStart(2, "0")}:${clock}` : clock;
}

function updateRecordingTimer() {
  const timer = $("#recordingTimer");
  const startedAt = Date.parse(state.live.recording_started_at || "");
  const active = Boolean(state.live.recording && Number.isFinite(startedAt));
  timer.hidden = !active;
  timer.querySelector("time").textContent = active
    ? formatRecordingDuration((Date.now() - startedAt) / 1000)
    : "00:00";
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
    const sensor = await api(`/api/sensors?base_url=${encodeURIComponent($("#setupSensorUrl").value.trim())}`);
    const dhtValid = sensor.dht_ok !== false && Number.isFinite(sensor.temperature_c) && Number.isFinite(sensor.humidity_percent);
    const sonarValid = sensor.sonar_ok === true && Number.isFinite(sensor.distance_cm);
    const imuValid = sensor.mpu_ok === true
      && [sensor.accel_g?.x, sensor.accel_g?.y, sensor.accel_g?.z, sensor.gyro_dps?.x, sensor.gyro_dps?.y, sensor.gyro_dps?.z, sensor.tilt_deg?.roll, sensor.tilt_deg?.pitch, sensor.tilt_deg?.yaw].every(Number.isFinite);
    updateExpeditionTelemetry(sensor, dhtValid, imuValid);
    if (!dhtValid && !sonarValid && !imuValid) {
      throw new Error(sensor.error || "No sensor readings available");
    }
    if (dhtValid) {
      setEnvValue("temperature", sensor.temperature_c, "°C");
      setEnvValue("humidity", sensor.humidity_percent, "%");
      $("#inspectionTemperature").textContent = `${sensor.temperature_c.toFixed(1)} °C`;
      $("#inspectionHumidity").textContent = `${sensor.humidity_percent.toFixed(1)} % RH`;
    } else {
      setEnvOffline(["temperature", "humidity"]);
      $("#inspectionTemperature").textContent = "—";
      $("#inspectionHumidity").textContent = "—";
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
    updateExpeditionTelemetry(null, false, false);
    $("#inspectionTemperature").textContent = "—";
    $("#inspectionHumidity").textContent = "—";
    state.currentDistance = null;
    setEnvOffline();
    setImuOffline();
    drawSensorCharts();
  }
}

function updateExpeditionTelemetry(sensor, dhtValid, imuValid) {
  $("#expeditionTemperature").textContent = dhtValid ? `${sensor.temperature_c.toFixed(1)} °C` : "—";
  $("#expeditionHumidity").textContent = dhtValid ? `${sensor.humidity_percent.toFixed(1)} % RH` : "—";
  $("#expeditionRoll").textContent = imuValid ? `${sensor.tilt_deg.roll.toFixed(1)}°` : "—";
  $("#expeditionPitch").textContent = imuValid ? `${sensor.tilt_deg.pitch.toFixed(1)}°` : "—";
  $("#expeditionYaw").textContent = imuValid ? `${sensor.tilt_deg.yaw.toFixed(1)}°` : "—";
  $("#expeditionAccel").textContent = imuValid ? [sensor.accel_g.x, sensor.accel_g.y, sensor.accel_g.z].map(value => value.toFixed(2)).join(" / ") + " g" : "—";
  $("#expeditionGyro").textContent = imuValid ? [sensor.gyro_dps.x, sensor.gyro_dps.y, sensor.gyro_dps.z].map(value => value.toFixed(1)).join(" / ") + " °/s" : "—";
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
    if (element) element.innerHTML = Number.isFinite(value) ? `${value.toFixed(digits)}${unit ? `<small>${unit}</small>` : ""}` : "—";
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
        throw new Error("Use the raw camera URL, for example http://192.168.0.119/jpg");
      }
      await api("/api/live/connect", {
        method: "POST",
        body: {
          stream_url: streamUrl,
          sensor_base_url: $("#setupSensorUrl").value.trim(),
          model_id: $("#liveModel").value || "depth-anything/DA3-BASE",
          process_res: Number($("#processRes").value),
          inference_fps: Number($("#inferenceFps").value),
          depth_enabled: Boolean($("#liveModel").value),
          semantic_enabled: $("#semanticEnabled").value === "true",
          semantic_fps: Number($("#semanticFps").value),
          camera_profile: $("#cameraProfile").value,
          low_light_mode: $("#lowLightMode").value,
          low_light_strength: Number($("#lowLightStrength").value),
          rotation: Number($("#cameraRotation").value),
        },
      });
      localStorage.setItem("pitdivers.cameraUrl", streamUrl);
      toast("Connecting", $("#liveModel").value
        ? "Camera appears first; DA3 depth follows after the model loads."
        : "Camera-only mode; depth inference will not load.");
    }
    await refreshLiveStatus(false);
  } catch (error) {
    toast("Connection failed", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function roverBaseUrl() {
  return $("#roverUrl").value.trim().replace(/\/$/, "");
}

function updateDriveControlAvailability() {
  const automated = Boolean(state.gamepad.running || state.autonomy.running);
  $$('[data-rover-command]').forEach((button) => {
    button.disabled = !state.rover.connected || automated;
  });
  $("#roverEmergencyStop").disabled = !state.rover.connected && !automated;
}

function renderRoverStatus() {
  const rover = state.rover;
  const dot = $("#roverStatusDot");
  const status = rover.status || {};
  dot.className = `status-dot ${rover.connected ? "online" : ""}`;
  $("#roverStatusText").textContent = rover.connected ? "Controls connected" : "Not connected";
  $("#roverStatusDetail").textContent = rover.connected
    ? `${status.mode || "human"} mode · ${status.motion || "stopped"} · speed ${status.speed ?? $("#roverSpeed").value}`
    : "Connect the separate motion controller";
  $("#roverConnectButton").textContent = rover.connected ? "Disconnect controls" : "Connect controls";
  $("#roverUrl").disabled = rover.connected;
  $("#expeditionDriveState").textContent = rover.connected ? "Connected" : "Disconnected";
  updateDriveControlAvailability();
  updateDriveStream();
}

async function refreshRoverStatus(silent = true) {
  if (!state.rover.connected) return;
  try {
    state.rover.status = await api(`/api/rover/status?base_url=${encodeURIComponent(roverBaseUrl())}`);
    renderRoverStatus();
  } catch (error) {
    stopRoverDrive(false);
    state.rover.connected = false;
    state.rover.status = null;
    renderRoverStatus();
    if (!silent) toast("Rover unavailable", error.message, "error");
  }
}

async function toggleRoverConnection() {
  const button = $("#roverConnectButton");
  button.disabled = true;
  try {
    if (state.rover.connected) {
      await stopRoverDrive(true);
      state.rover.connected = false;
      state.rover.status = null;
      toast("Rover controls disconnected");
    } else {
      const baseUrl = roverBaseUrl();
      if (!/^https?:\/\/[^\s]+$/i.test(baseUrl)) throw new Error("Use the rover ESP URL, for example http://192.168.0.70");
      state.rover.status = await api("/api/rover/connect", { method: "POST", body: { base_url: baseUrl } });
      state.rover.connected = true;
      localStorage.setItem("pitdivers.roverUrl", baseUrl);
      $("#setupWheelUrl").value = baseUrl;
      toast("Rover controls ready", "Human mode enabled. Hold a direction to drive.");
    }
  } catch (error) {
    state.rover.connected = false;
    state.rover.status = null;
    toast("Rover connection failed", error.message, "error");
  } finally {
    button.disabled = false;
    renderRoverStatus();
  }
}

async function sendRoverCommand(command, reportErrors = true) {
  if (!state.rover.connected || (state.rover.requestPending && command !== "stop")) return;
  state.rover.requestPending = true;
  try {
    await api("/api/rover/command", {
      method: "POST",
      body: { base_url: roverBaseUrl(), command, speed: Number($("#roverSpeed").value) },
    });
    state.rover.status = { ...(state.rover.status || {}), mode: "human", motion: command === "stop" ? "stopped" : command, speed: Number($("#roverSpeed").value) };
    renderRoverStatus();
  } catch (error) {
    if (reportErrors) toast("Rover command failed", error.message, "error");
  } finally {
    state.rover.requestPending = false;
  }
}

function startRoverDrive(command) {
  if (!state.rover.connected || command === "stop" || state.rover.activeCommand === command) return;
  stopRoverDrive(false);
  state.rover.activeCommand = command;
  $(`[data-rover-command="${command}"]`)?.classList.add("active");
  sendRoverCommand(command);
  state.rover.repeatTimer = window.setInterval(() => sendRoverCommand(command, false), 300);
}

async function stopRoverDrive(sendStop = true) {
  if (state.rover.repeatTimer) window.clearInterval(state.rover.repeatTimer);
  state.rover.repeatTimer = null;
  state.rover.activeCommand = null;
  $$('[data-rover-command]').forEach((button) => button.classList.remove("active"));
  if (sendStop && state.rover.connected) await sendRoverCommand("stop");
}

function renderGamepadStatus() {
  const running = Boolean(state.gamepad.running);
  const pill = $("#gamepadStatus");
  pill.textContent = running ? "Running" : "Stopped";
  pill.classList.toggle("accent", running);
  $("#gamepadStartButton").disabled = running;
  $("#gamepadStopButton").disabled = !running;
  updateDriveControlAvailability();
}

async function refreshGamepadStatus() {
  try {
    state.gamepad = await api("/api/gamepad/status");
  } catch (error) {
    state.gamepad = { running: false, error: error.message };
  }
  renderGamepadStatus();
}

async function startGamepadBridge() {
  const button = $("#gamepadStartButton");
  button.disabled = true;
  try {
    await stopRoverDrive(true);
    state.gamepad = await api("/api/gamepad/start", {
      method: "POST",
      body: {
        base_url: roverBaseUrl(),
        api_key: $("#controlApiKey").value,
        max_speed: Number($("#roverSpeed").value),
      },
    });
    toast("Controller bridge started", "The PC is now reading the first XInput controller.");
  } catch (error) {
    toast("Controller could not start", error.message, "error");
  } finally {
    await refreshGamepadStatus();
  }
}

async function stopGamepadBridge(report = true) {
  try {
    state.gamepad = await api("/api/gamepad/stop", { method: "POST" });
    if (report) toast("Controller stopped", "The rover was returned to Human mode.");
  } catch (error) {
    if (report) toast("Controller stop failed", error.message, "error");
  } finally {
    renderGamepadStatus();
  }
}

function renderAutonomyStatus() {
  const status = state.autonomy || {};
  const pill = $("#autonomyStatus");
  pill.textContent = status.state || "idle";
  pill.classList.toggle("accent", status.running || status.state === "arrived");
  $("#autonomyDetail").textContent = status.message || "Connect the camera and motion ESP first.";
  $("#autonomyStartButton").disabled = Boolean(status.running);
  $("#autonomyStopButton").disabled = !status.running && !["blocked", "arrived", "error"].includes(status.state);
  updateDriveControlAvailability();
  renderAutonomyConsole();
}

function renderAutonomyConsole() {
  const status = state.autonomy || {};
  const body = $("#autonomyConsoleBody");
  if (!body) return;
  const stayAtBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 50;
  $("#autonomyConsoleStatus").textContent = status.state || "idle";
  $("#autonomyConsoleStatus").classList.toggle("accent", Boolean(status.running) || status.state === "arrived");
  $("#autonomyConsoleTarget").textContent = status.target || "—";
  $("#autonomyConsoleAction").textContent = status.action || "stopped";
  $("#autonomyConsoleSteps").textContent = String(status.steps || 0);
  const logs = status.logs || [];
  body.textContent = logs.length ? logs.map((entry) => {
    const stamp = entry.at ? new Date(entry.at).toLocaleTimeString([], { hour12: false }) : "--:--:--";
    return `[${stamp}] ${String(entry.level || "info").toUpperCase().padEnd(7)} ${entry.message}`;
  }).join("\n") : "Waiting for an autonomy task…";
  if (stayAtBottom) body.scrollTop = body.scrollHeight;
}

function openAutonomyConsole() {
  renderAutonomyConsole();
  const dialog = $("#autonomyConsoleDialog");
  if (!dialog.open) dialog.showModal();
  requestAnimationFrame(() => { $("#autonomyConsoleBody").scrollTop = $("#autonomyConsoleBody").scrollHeight; });
}

async function refreshAutonomyStatus() {
  try {
    state.autonomy = await api("/api/autonomy/status");
  } catch (error) {
    state.autonomy = { state: "error", running: false, message: error.message };
  }
  renderAutonomyStatus();
}

async function refreshOllamaModels() {
  const url = $("#ollamaUrl").value;
  try {
    const result = await api(`/api/autonomy/models?ollama_url=${encodeURIComponent(url)}`);
    $("#ollamaModels").innerHTML = (result.models || [])
      .map((model) => `<option value="${escapeHtml(model)}"></option>`).join("");
  } catch { /* Ollama is optional until Llama mode is enabled. */ }
}

function syncAutonomyMission() {
  const exploring = $("#autonomyMission").value === "explore";
  $("#autonomyTarget").disabled = exploring;
  $("#ollamaModel").disabled = exploring;
  $("#autonomyUseLlama").disabled = exploring;
  $("#autonomyStartButton").textContent = exploring ? "Explore room" : "Find object";
}

async function startAutonomy() {
  const button = $("#autonomyStartButton");
  let startError = null;
  button.disabled = true;
  state.autonomy = {
    ...(state.autonomy || {}), state: "starting", running: false,
    logs: [{ at: new Date().toISOString(), level: "info", message: "Submitting autonomy task to the dashboard…" }],
  };
  openAutonomyConsole();
  try {
    const baseUrl = roverBaseUrl();
    const apiKey = $("#controlApiKey").value.trim();
    const mission = $("#autonomyMission").value;
    const target = mission === "explore" ? "ROOM" : $("#autonomyTarget").value.trim();
    const speed = Number($("#autonomySpeed").value);
    const useVision = mission === "find" && $("#autonomyUseLlama").checked;
    const model = $("#ollamaModel").value.trim();
    if (!/^https?:\/\/[^\s]+$/i.test(baseUrl)) throw new Error("Enter the motion ESP URL, including http://");
    if (!apiKey) throw new Error("Enter the motion ESP API key");
    if (mission === "find" && !target) throw new Error("Enter the object you want the rover to find");
    if (!Number.isFinite(speed) || speed < 60 || speed > 220) throw new Error("AI speed must be between 60 and 220");
    if (useVision && !model) throw new Error("Select an installed Ollama vision model, such as gemma3:12b");
    await stopRoverDrive(true);
    state.autonomy = await api("/api/autonomy/start", {
      method: "POST",
      body: {
        base_url: baseUrl,
        api_key: apiKey,
        mission,
        target,
        speed,
        use_llama: useVision,
        ollama_url: $("#ollamaUrl").value,
        model,
      },
    });
    toast("Autonomy started", mission === "explore" ? "Exploring with depth and sonar." : `Searching for ${state.autonomy.target}.`);
  } catch (error) {
    startError = error;
    toast("Autonomy could not start", error.message, "error");
  } finally {
    await refreshAutonomyStatus();
    if (startError) {
      state.autonomy = {
        ...(state.autonomy || {}), state: "error", running: false, message: startError.message,
        logs: [...(state.autonomy.logs || []), { at: new Date().toISOString(), level: "error", message: startError.message }],
      };
      renderAutonomyStatus();
    }
    await refreshGamepadStatus();
  }
}

async function stopAutonomy(report = true) {
  try {
    state.autonomy = await api("/api/autonomy/stop", { method: "POST" });
    if (report) toast("Autonomy stopped", "The rover was stopped and returned to Human mode.");
  } catch (error) {
    if (report) toast("Autonomy stop failed", error.message, "error");
  } finally {
    renderAutonomyStatus();
  }
}

async function emergencyStopAll() {
  await Promise.allSettled([stopAutonomy(false), stopGamepadBridge(false), stopRoverDrive(true)]);
  toast("Emergency stop sent", "Manual, controller, and AI motion were stopped.");
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
  const liveValue = liveSelect.options.length ? liveSelect.value : "depth-anything/DA3-BASE";
  const reconstructValue = reconstructSelect.value || "depth-anything/DA3-BASE";
  const options = state.models.map((model) => {
    const cached = model.cached ? "" : " · download first";
    return `<option value="${escapeHtml(model.id)}" ${model.cached ? "" : "disabled"}>${escapeHtml(model.name + cached)}</option>`;
  }).join("");
  liveSelect.innerHTML = `<option value="">Camera only · depth disabled</option>${options}`;
  reconstructSelect.innerHTML = options;
  if (liveValue === "") liveSelect.value = "";
  else if ([...liveSelect.options].some((option) => option.value === liveValue && !option.disabled)) liveSelect.value = liveValue;
  else if ([...liveSelect.options].some((option) => option.value === "depth-anything/DA3-BASE" && !option.disabled)) liveSelect.value = "depth-anything/DA3-BASE";
  if ([...reconstructSelect.options].some((option) => option.value === reconstructValue && !option.disabled)) reconstructSelect.value = reconstructValue;
  else reconstructSelect.value = [...reconstructSelect.options].find((option) => !option.disabled)?.value || "";
  syncDepthControls();
}

function syncDepthControls() {
  const depthEnabled = Boolean($("#liveModel").value);
  const semanticEnabled = $("#semanticEnabled").value === "true";
  const connected = state.live.state !== "disconnected";
  $("#processRes").disabled = connected || !depthEnabled;
  $("#inferenceFps").disabled = connected || !depthEnabled;
  $("#semanticFps").disabled = connected || !semanticEnabled;
  if (!connected) renderLiveStatus();
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
          ${capture.manifest?.video_file ? `<a class="button secondary" href="/api/captures/${encodeURIComponent(capture.name)}/video" target="_blank" rel="noopener">Video</a>` : ""}
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
        <span class="asset-type">${run.semantic ? "SEMANTIC GLB" : "GLB SCENE"}</span>
      </div>
      <div class="asset-body">
        <div class="asset-title-row"><h3>${escapeHtml(run.name)}</h3><time>${escapeHtml(formatDate(run.updated_at))}</time></div>
        <div class="asset-meta"><span>${formatBytes(run.size_bytes)}</span><span>${run.semantic ? `${run.object_count} object candidates` : "Interactive point cloud"}</span></div>
        <div class="asset-actions">
          <button class="button primary" data-view-run="${escapeHtml(run.name)}">Open 3D viewer</button>
          <button class="button secondary" data-rename-run="${escapeHtml(run.name)}">Rename</button>
          <a class="button secondary" href="${escapeHtml(run.download_url)}">Download</a>
          ${run.report_url ? `<a class="button secondary" href="${escapeHtml(run.report_url)}" target="_blank" rel="noopener">Evidence</a>` : ""}
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

async function openViewer(runName) {
  const run = state.runs.find((item) => item.name === runName);
  if (!run) return;
  $("#viewerTitle").textContent = runName;
  const viewer = $("#sceneViewer");
  viewer.setAttribute("auto-rotate", "");
  viewer.cameraTarget = "auto auto auto";
  viewer.cameraOrbit = "auto auto auto";
  $("#semanticHotspot").hidden = true;
  $("#clearSemanticHighlight").hidden = true;
  viewer.src = `${run.model_url}?t=${Date.now()}`;
  viewer.addEventListener("load", applySemanticReviewMaterials, {once: true});
  $("#downloadGlb").href = run.download_url;
  const semanticPanel = $("#semanticViewerPanel");
  semanticPanel.hidden = !run.semantic;
  $("#semanticObjectList").innerHTML = "";
  state.semanticObjects = [];
  state.semanticRegistry = null;
  state.semanticRun = runName;
  state.semanticSelected = null;
  $("#semanticInspector").hidden = true;
  if (run.semantic) {
    $("#semanticReportLink").href = run.report_url || run.objects_url;
    try {
      const registry = await api(run.objects_url);
      state.semanticObjects = registry.objects;
      state.semanticRegistry = registry;
      renderSemanticObjects();
    } catch (error) {
      $("#semanticObjectList").innerHTML = `<p>Object registry unavailable: ${escapeHtml(error.message)}</p>`;
    }
  }
  $("#viewerDialog").showModal();
}

function applySemanticReviewMaterials() {
  const rejected = new Set(state.semanticObjects
    .filter((item) => semanticStatus(item) === "rejected")
    .flatMap((item) => item.geometry_ids || [item.object_id]));
  $("#sceneViewer").model?.materials?.forEach((material) => {
    if (!rejected.has(material.name)) return;
    try {
      material.pbrMetallicRoughness.setBaseColorFactor([0.03, 0.03, 0.03, 0.02]);
      material.setAlphaMode("BLEND");
    } catch (error) { console.warn(`Could not hide rejected material ${material.name}`, error); }
  });
}

function semanticStatus(item) {
  return item.review?.status || "candidate";
}

function renderSemanticObjects() {
  const objects = state.semanticObjects.filter((item) => state.semanticFilter === "all" || semanticStatus(item) === state.semanticFilter);
  $("#semanticObjectCount").textContent = state.semanticObjects.filter((item) => semanticStatus(item) !== "rejected").length;
  $("#semanticObjectList").innerHTML = objects.map((item) => `
    <button type="button" class="semantic-object ${semanticStatus(item)} ${state.semanticSelected === item.object_id ? "selected" : ""}" data-semantic-object="${escapeHtml(item.object_id)}">
      <span class="semantic-object-title"><strong>${escapeHtml(item.label)}</strong><span>${Math.round(item.confidence * 100)}%</span></span>
      <p>${escapeHtml(item.object_id)} · ${item.observations} views · ${Number(item.point_count).toLocaleString()} points</p>
      <p>${Math.round((item.surface_support || 0) * 100)}% surface support · ${semanticStatus(item)}</p>
    </button>`).join("") || "<p class='semantic-empty'>No objects in this review state.</p>";
}

function showSemanticInspector(item) {
  const calibration = state.semanticRegistry?.calibration;
  const extent = item.bbox_max.map((value, index) => Math.max(0, Number(value) - Number(item.bbox_min[index])));
  const scale = calibration?.meters_per_unit;
  const suffix = scale ? "m" : "units";
  const display = extent.map((value) => (value * (scale || 1)).toFixed(2));
  $("#semanticInspector").hidden = false;
  $("#semanticInspectorId").textContent = item.object_id;
  $("#semanticLabel").value = item.label;
  $("#semanticNote").value = item.review?.note || "";
  $("#semanticDimensions").textContent = `Size X ${display[0]} × Y ${display[1]} × Z ${display[2]} ${suffix}`;
  $("#semanticCalibrationStatus").textContent = scale
    ? `Calibrated · ${Number(scale).toFixed(3)} metres per scene unit`
    : "Relative DA3 units · enter one known dimension to set scale";
  $("#semanticEvidence").innerHTML = (item.mask_files || []).slice(0, 4).map((mask) => {
    const url = `/api/runs/${encodeURIComponent(state.semanticRun)}/semantic/${mask}`;
    return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener"><img src="${escapeHtml(url)}" alt="Evidence mask for ${escapeHtml(item.object_id)}"></a>`;
  }).join("");
  $("#semanticMergeTarget").innerHTML = `<option value="">Merge with…</option>${state.semanticObjects
    .filter((candidate) => candidate.object_id !== item.object_id && semanticStatus(candidate) !== "rejected")
    .map((candidate) => `<option value="${escapeHtml(candidate.object_id)}">${escapeHtml(candidate.object_id)} · ${escapeHtml(candidate.label)}</option>`).join("")}`;
}

function focusSemanticObject(objectId) {
  const item = state.semanticObjects.find((candidate) => candidate.object_id === objectId);
  if (!item) return;
  state.semanticSelected = objectId;
  showSemanticInspector(item);
  const viewer = $("#sceneViewer");
  const center = item.centroid_world.map(Number);
  const size = item.bbox_max.map((value, index) => Number(value) - Number(item.bbox_min[index]));
  const distance = Math.max(Math.hypot(...size) * 2.6, 0.12);
  viewer.removeAttribute("auto-rotate");
  const hotspot = $("#semanticHotspot");
  const position = `${center[0]}m ${center[1]}m ${center[2]}m`;
  hotspot.hidden = false;
  hotspot.dataset.position = position;
  $("#semanticHotspotLabel").textContent = objectId;
  viewer.updateHotspot?.({name: "hotspot-selected", position});
  $("#clearSemanticHighlight").hidden = false;
  if (viewer.model?.materials) {
    const semanticIds = new Set(state.semanticObjects.flatMap((candidate) => candidate.geometry_ids || [candidate.object_id]));
    const selectedIds = new Set(item.geometry_ids || [item.object_id]);
    viewer.model.materials.forEach((material) => {
      try {
        if (material.name === "geometry_0") {
          material.pbrMetallicRoughness.setBaseColorFactor([0.13, 0.13, 0.13, 0.16]);
          material.setAlphaMode("BLEND");
        } else if (semanticIds.has(material.name)) {
          const selected = selectedIds.has(material.name);
          material.pbrMetallicRoughness.setBaseColorFactor(selected ? [1, 1, 1, 1] : [0.03, 0.03, 0.03, 0.02]);
          material.setAlphaMode(selected ? "OPAQUE" : "BLEND");
        }
      } catch (error) {
        console.warn(`Could not update material ${material.name}`, error);
      }
    });
  }
  viewer.cameraTarget = position;
  viewer.cameraOrbit = `auto auto ${distance}m`;
  viewer.jumpCameraToGoal?.();
  renderSemanticObjects();
}

function clearSemanticHighlight() {
  const viewer = $("#sceneViewer");
  viewer.model?.materials?.forEach((material) => {
    try {
      material.pbrMetallicRoughness.setBaseColorFactor([1, 1, 1, 1]);
      material.setAlphaMode("OPAQUE");
    } catch (error) {
      console.warn(`Could not reset material ${material.name}`, error);
    }
  });
  $("#semanticHotspot").hidden = true;
  $("#clearSemanticHighlight").hidden = true;
  $$("[data-semantic-object]").forEach((button) => button.classList.remove("selected"));
  state.semanticSelected = null;
  $("#semanticInspector").hidden = true;
  viewer.cameraTarget = "auto auto auto";
  viewer.cameraOrbit = "auto auto auto";
  viewer.jumpCameraToGoal?.();
}

async function reviewSemanticObject(status) {
  const item = state.semanticObjects.find((candidate) => candidate.object_id === state.semanticSelected);
  if (!item) return;
  try {
    const updated = await api(`/api/runs/${encodeURIComponent(state.semanticRun)}/semantic/review/${encodeURIComponent(item.object_id)}`, {
      method: "POST",
      body: {status, label: $("#semanticLabel").value, note: $("#semanticNote").value},
    });
    Object.assign(item, updated);
    applySemanticReviewMaterials();
    renderSemanticObjects();
    showSemanticInspector(item);
    toast("Object review saved", `${item.object_id} is ${status}.`);
  } catch (error) { toast("Could not save review", error.message, "error"); }
}

async function reloadSemanticRegistry(selectedId = null) {
  const run = state.runs.find((item) => item.name === state.semanticRun);
  if (!run?.objects_url) return;
  const registry = await api(`${run.objects_url}?t=${Date.now()}`);
  state.semanticRegistry = registry;
  state.semanticObjects = registry.objects;
  state.semanticSelected = selectedId;
  renderSemanticObjects();
  const selected = state.semanticObjects.find((item) => item.object_id === selectedId);
  if (selected) showSemanticInspector(selected);
}

async function calibrateSemanticScene() {
  const knownSize = Number($("#semanticKnownSize").value);
  if (!state.semanticSelected || !(knownSize > 0)) return toast("Known size required", "Enter the selected dimension in metres.", "error");
  try {
    const calibration = await api(`/api/runs/${encodeURIComponent(state.semanticRun)}/semantic/calibrate`, {
      method: "POST",
      body: {object_id: state.semanticSelected, axis: Number($("#semanticCalibrationAxis").value), known_extent_m: knownSize},
    });
    state.semanticRegistry.calibration = calibration;
    showSemanticInspector(state.semanticObjects.find((item) => item.object_id === state.semanticSelected));
    toast("Metric scale saved", `${Number(calibration.meters_per_unit).toFixed(3)} metres per scene unit.`);
  } catch (error) { toast("Could not calibrate", error.message, "error"); }
}

async function mergeSemanticObjects() {
  const target = $("#semanticMergeTarget").value;
  if (!state.semanticSelected || !target) return;
  try {
    const merged = await api(`/api/runs/${encodeURIComponent(state.semanticRun)}/semantic/merge`, {
      method: "POST",
      body: {object_ids: [state.semanticSelected, target], label: $("#semanticLabel").value},
    });
    const removed = new Set([state.semanticSelected, target]);
    state.semanticObjects = state.semanticObjects.filter((item) => !removed.has(item.object_id));
    state.semanticObjects.push(merged);
    state.semanticSelected = merged.object_id;
    renderSemanticObjects();
    focusSemanticObject(merged.object_id);
    toast("Objects merged", `${merged.geometry_ids.length} geometry groups now share ${merged.object_id}.`);
  } catch (error) { toast("Could not merge", error.message, "error"); }
}

async function splitSemanticObject() {
  if (!state.semanticSelected) return;
  try {
    const result = await api(`/api/runs/${encodeURIComponent(state.semanticRun)}/semantic/split/${encodeURIComponent(state.semanticSelected)}`, {
      method: "POST", body: {axis: Number($("#semanticSplitAxis").value)},
    });
    const childId = result.objects[0].object_id;
    await reloadSemanticRegistry(childId);
    const run = state.runs.find((item) => item.name === state.semanticRun);
    const viewer = $("#sceneViewer");
    viewer.addEventListener("load", () => focusSemanticObject(childId), {once: true});
    viewer.src = `${run.model_url}?t=${Date.now()}`;
    toast("Geometry split", `${state.semanticSelected} is ready for separate review.`);
  } catch (error) { toast("Could not split", error.message, "error"); }
}

function closeDialog(dialog) {
  if (dialog.id === "viewerDialog") $("#sceneViewer").removeAttribute("src");
  if (dialog.id === "chartDialog") state.openChart = null;
  if (dialog.id === "logDialog") state.logPopoutJob = null;
  dialog.close();
}

function bindEvents() {
  $("#expeditionStart").addEventListener("click", startExpedition);
  $("#expeditionStop").addEventListener("click", stopExpedition);
  $("#expeditionEmergencyStop").addEventListener("click", emergencyStopAll);
  $("#expeditionMapOpen").addEventListener("click", () => $("#expeditionMapDialog").showModal());
  $("#reportMapOpen").addEventListener("click", () => $("#expeditionMapDialog").showModal());
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => setTab(button.dataset.tab)));
  $("#connectButton").addEventListener("click", toggleConnection);
  $("#driveDetection").addEventListener("change", () => updateDriveStream(true));
  $("#driveViewSource").addEventListener("change", () => updateDriveStream(true));
  $("#lowLightMode").addEventListener("change", () => applyLowLightSettings(true));
  $("#lowLightStrength").addEventListener("input", () => applyLowLightSettings(false));
  $("#roverConnectButton").addEventListener("click", toggleRoverConnection);
  $("#roverSpeed").addEventListener("input", () => { $("#roverSpeedValue").textContent = $("#roverSpeed").value; });
  $("#roverEmergencyStop").addEventListener("click", emergencyStopAll);
  $("#gamepadStartButton").addEventListener("click", startGamepadBridge);
  $("#gamepadStopButton").addEventListener("click", () => stopGamepadBridge(true));
  $("#autonomyStartButton").addEventListener("click", startAutonomy);
  $("#autonomyMission").addEventListener("change", syncAutonomyMission);
  $("#autonomyStopButton").addEventListener("click", () => stopAutonomy(true));
  $("#autonomyConsoleButton").addEventListener("click", openAutonomyConsole);
  $("#autonomyConsoleStop").addEventListener("click", () => stopAutonomy(true));
  ["showRawFeed", "showDepthFeed", "showSemanticFeed"].forEach((id) => {
    $(`#${id}`).addEventListener("change", () => applyFeedVisibility(true));
  });
  $$('[data-rover-command]').forEach((button) => {
    button.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      button.setPointerCapture?.(event.pointerId);
      const command = button.dataset.roverCommand;
      if (command === "stop") stopRoverDrive(true);
      else startRoverDrive(command);
    });
    button.addEventListener("pointerup", () => stopRoverDrive(true));
    button.addEventListener("pointercancel", () => stopRoverDrive(true));
  });
  const roverKeys = { w: "forward", arrowup: "forward", a: "left", arrowleft: "left", s: "backward", arrowdown: "backward", d: "right", arrowright: "right" };
  window.addEventListener("keydown", (event) => {
    if (event.repeat || /^(INPUT|SELECT|TEXTAREA)$/.test(event.target?.tagName || "")) return;
    const command = roverKeys[event.key.toLowerCase()];
    if (command && state.rover.connected) { event.preventDefault(); startRoverDrive(command); }
    if (event.key === " " && state.rover.connected) { event.preventDefault(); stopRoverDrive(true); }
  });
  window.addEventListener("keyup", (event) => {
    const command = roverKeys[event.key.toLowerCase()];
    if (command && state.rover.activeCommand === command) { event.preventDefault(); stopRoverDrive(true); }
  });
  window.addEventListener("blur", () => stopRoverDrive(true));
  document.addEventListener("visibilitychange", () => { if (document.hidden) stopRoverDrive(true); });
  $("#liveModel").addEventListener("change", syncDepthControls);
  $("#semanticEnabled").addEventListener("change", syncDepthControls);
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
  $("#clearSemanticHighlight").addEventListener("click", clearSemanticHighlight);
  $("#closeSemanticInspector").addEventListener("click", () => { $("#semanticInspector").hidden = true; });
  $("#calibrateSemantic").addEventListener("click", calibrateSemanticScene);
  $("#mergeSemantic").addEventListener("click", mergeSemanticObjects);
  $("#splitSemantic").addEventListener("click", splitSemanticObject);
  $$('[data-semantic-review]').forEach((button) => button.addEventListener("click", () => reviewSemanticObject(button.dataset.semanticReview)));
  $$('[data-semantic-filter]').forEach((button) => button.addEventListener("click", () => {
    state.semanticFilter = button.dataset.semanticFilter;
    $$('[data-semantic-filter]').forEach((candidate) => candidate.classList.toggle("active", candidate === button));
    renderSemanticObjects();
  }));
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
    const semanticObject = event.target.closest("[data-semantic-object]");
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
    if (semanticObject) focusSemanticObject(semanticObject.dataset.semanticObject);
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
  $("#semanticStream").addEventListener("load", () => $("#semanticFrameWrap").classList.add("streaming"));
}

async function refreshInspectionReports() {
  try {
    const [captures, rooms, reports, remote] = await Promise.all([
      api("/api/captures"), api("/api/inspection/rooms"), api("/api/inspection/reports"), api("/api/remote/da3/config"),
    ]);
    state.reports = reports;
    const captureSelect = $("#reportCapture");
    const roomSelect = $("#reportRoom");
    const captureValue = captureSelect.value;
    const roomValue = roomSelect.value;
    captureSelect.innerHTML = captures.length
      ? captures.map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)} · ${item.images} frames</option>`).join("")
      : '<option value="">No captures saved</option>';
    roomSelect.innerHTML = rooms.length
      ? rooms.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.id)} · ${escapeHtml(formatDate(item.updated_at))}</option>`).join("")
      : '<option value="">No LiDAR rooms saved</option>';
    if (captures.some((item) => item.name === captureValue)) captureSelect.value = captureValue;
    if (rooms.some((item) => item.id === roomValue)) roomSelect.value = roomValue;
    $("#remoteDa3Status").textContent = remote.configured
      ? `DA3 PC: ${remote.url}`
      : "Remote DA3 is not configured on this laptop. Set PITDIVERS_DA3_REMOTE_URL and PITDIVERS_REMOTE_TOKEN.";
    $("#reportList").innerHTML = reports.length ? reports.map((item) => {
      const base = `/api/inspection/reports/${encodeURIComponent(item.id)}`;
      return `<article class="inspection-report-row"><div><strong>${escapeHtml(item.asset)}</strong><small>${escapeHtml(item.created_at)} · ${escapeHtml(item.capture)} · LiDAR ${escapeHtml(item.room_id)}</small><small>${escapeHtml(item.temperature)} · ${escapeHtml(item.humidity)}</small><small>${escapeHtml(item.source_association || "")}</small></div><div><a class="button primary" href="${base}/report.html" target="_blank" rel="noopener">Open interactive report</a><a class="button secondary" href="${base}/map.svg" target="_blank" rel="noopener">Map</a><a class="button secondary" href="${base}/temperature.svg" target="_blank" rel="noopener">Temperature</a><a class="button secondary" href="${base}/humidity.svg" target="_blank" rel="noopener">Humidity</a><a class="button secondary" href="${base}/source.json" download>LiDAR JSON</a>${item.sensor_file ? `<a class="button secondary" href="${base}/sensors.jsonl" download>Sensor data</a>` : ""}${item.video_url ? `<a class="button secondary" href="${escapeHtml(item.video_url)}" target="_blank" rel="noopener">Video</a>` : ""}${item.remote_model_url ? `<a class="button secondary" href="${escapeHtml(item.remote_model_url)}" target="_blank" rel="noopener">3D model</a>` : ""}</div></article>`;
    }).join("") : '<p>No reports yet.</p>';
  } catch (error) {
    $("#reportProgress").textContent = error.message;
  }
}

async function sendCaptureToDa3() {
  const capture = $("#reportCapture").value;
  const button = $("#sendDa3Button");
  if (!capture) return;
  button.disabled = true;
  $("#remoteDa3Status").textContent = "Uploading selected frames to the DA3 PC…";
  try {
    const result = await api(`/api/remote/da3/send/${encodeURIComponent(capture)}`, { method: "POST" });
    $("#remoteDa3Status").textContent = `DA3 queued on PC: ${result.job.id}. Click Check DA3 for progress.`;
  } catch (error) {
    $("#remoteDa3Status").textContent = error.message;
    toast("DA3 transfer failed", error.message, "error");
  } finally { button.disabled = false; }
}

async function checkRemoteDa3() {
  const capture = $("#reportCapture").value;
  if (!capture) return;
  try {
    const result = await api(`/api/remote/da3/status/${encodeURIComponent(capture)}`);
    const link = result.model_url ? ` Model: ${result.model_url}` : "";
    $("#remoteDa3Status").textContent = `DA3: ${result.state}${result.stage ? ` · ${result.stage}` : ""}${result.error ? ` · ${result.error}` : ""}${link}`;
    if (result.model_url) {
      for (const report of state.reports.filter(item => item.capture === capture && !item.model_file)) {
        try { await api(`/api/inspection/reports/${encodeURIComponent(report.id)}/attach-model`, { method: "POST" }); }
        catch (error) { $("#remoteDa3Status").textContent += ` · Could not add GLB to ${report.id}: ${error.message}`; }
      }
      await refreshInspectionReports();
    }
    if (result.model_url) window.open(result.model_url, "_blank", "noopener");
  } catch (error) { $("#remoteDa3Status").textContent = error.message; }
}

async function createInspectionReport() {
  const button = $("#createReportButton");
  button.disabled = true;
  $("#reportProgress").textContent = "Building report and evidence bundle…";
  try {
    const result = await api("/api/inspection/reports", {
      method: "POST",
      body: {
        capture_name: $("#reportCapture").value,
        room_id: $("#reportRoom").value,
        asset: $("#reportAsset").value.trim(),
        notes: $("#reportNotes").value.trim(),
        use_ai: $("#reportUseAi").checked,
        model: $("#reportModel").value.trim(),
      },
    });
    $("#reportProgress").textContent = `Report ${result.id} created. AI: ${result.ai.status}.`;
    await refreshInspectionReports();
    window.open(`/api/inspection/reports/${encodeURIComponent(result.id)}/report.html`, "_blank", "noopener");
  } catch (error) {
    $("#reportProgress").textContent = error.message;
    toast("Report failed", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

const expedition = { capture: null, roomId: null, reportId: null, remoteTimer: null, mapRevision: null };

function drawMiniMap(canvas, room) {
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#091720"; ctx.fillRect(0, 0, canvas.width, canvas.height);
  const cells = room?.cells || [];
  if (!cells.length) { ctx.fillStyle = "#a5b8c3"; ctx.fillText("Waiting for LiDAR map", 20, 35); return; }
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const cell of cells) { x0 = Math.min(x0, cell[0]); x1 = Math.max(x1, cell[0]); y0 = Math.min(y0, cell[1]); y1 = Math.max(y1, cell[1]); }
  const scale = Math.min((canvas.width - 28) / Math.max(1, x1 - x0 + 1), (canvas.height - 28) / Math.max(1, y1 - y0 + 1));
  const ox = (canvas.width - (x1 - x0 + 1) * scale) / 2, oy = (canvas.height - (y1 - y0 + 1) * scale) / 2;
  for (const [x, y, value] of cells) {
    ctx.fillStyle = value > 1 ? "#c3d5dd" : value < -0.4 ? "#25465a" : "#3a5866";
    ctx.fillRect(ox + (x - x0) * scale, oy + (y - y0) * scale, Math.max(1, scale), Math.max(1, scale));
  }
  const path = room.path || [];
  if (path.length) {
    ctx.strokeStyle = "#5fe0b6"; ctx.lineWidth = 2; ctx.beginPath();
    path.forEach((p, i) => { const x = ox + (p[0] / room.resolution - x0) * scale, y = oy + (p[1] / room.resolution - y0) * scale; i ? ctx.lineTo(x,y) : ctx.moveTo(x,y); });
    ctx.stroke();
  }
}

function drawExpeditionMap(room) {
  drawMiniMap($("#expeditionMap"), room);
  drawMiniMap($("#reportMap"), room);
}

async function refreshExpeditionMap() {
  if (!$("#page-expedition").classList.contains("active") && !$("#page-reports").classList.contains("active") && !expedition.capture) return;
  try {
    const map = await api("/api/expedition/map");
    $("#expeditionMapState").textContent = `${map.network?.lidar?.running ? "Live" : "Last scan"} · ${map.map?.cells?.length || 0} cells`;
    if (map.revision !== expedition.mapRevision) { expedition.mapRevision = map.revision; drawExpeditionMap(map.map); }
    expedition.roomId = map.run_id || expedition.roomId;
  } catch (error) { $("#expeditionMapState").textContent = "Map unavailable"; }
}

async function waitForExpeditionCamera() {
  for (let i = 0; i < 25; i++) {
    await refreshLiveStatus(false);
    if (state.live.width && state.live.height) return;
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error("Camera did not become ready. Check its URL in Setup.");
}

async function startExpedition() {
  const button = $("#expeditionStart"); button.disabled = true;
  let lidarStarted = false;
  $("#expeditionStatus").textContent = "Connecting camera and rover…";
  try {
    if (state.live.recording) throw new Error("Another camera recording is already active.");
    if (state.live.state === "disconnected") {
      $("#liveModel").value = "";
      $("#semanticEnabled").value = "false";
      await toggleConnection();
    }
    await waitForExpeditionCamera();
    if (!state.rover.connected) await toggleRoverConnection();
    if (!state.rover.connected) throw new Error("Wheel controller is unavailable. Check Setup.");
    await api("/api/expedition/lidar/start", { method: "POST" });
    lidarStarted = true;
    const capture = await api("/api/live/record/start", { method: "POST", body: {
      name: `expedition_${new Date().toISOString().replace(/[^0-9]/g, "").slice(0, 14)}`,
      keyframe_fps: 2, stable_only: false,
    }});
    expedition.capture = capture.name;
    expedition.reportId = null;
    $("#expeditionReportLink").hidden = true;
    $("#expeditionStop").disabled = false;
    $("#expeditionStatus").textContent = `Recording ${capture.name}. Camera, LiDAR and sensors are active.`;
    await refreshLiveStatus(false);
  } catch (error) {
    if (lidarStarted) try { await api("/api/expedition/lidar/stop", { method: "POST" }); } catch { /* Keep the start error. */ }
    $("#expeditionStatus").textContent = error.message;
    toast("Expedition could not start", error.message, "error");
    button.disabled = false;
  }
}

async function finishExpeditionReport(capture, roomId) {
  const key = $("#expeditionOpenRouterKey").value;
  const asset = $("#expeditionAsset").value.trim() || `Expedition ${capture}`;
  const model = $("#expeditionModel").value.trim();
  const report = await api("/api/inspection/reports", { method: "POST", body: {
    capture_name: capture, room_id: roomId, asset,
    notes: $("#expeditionNotes").value.trim(), use_ai: true,
    model, openrouter_api_key: key,
  }});
  $("#expeditionOpenRouterKey").value = "";
  expedition.reportId = report.id;
  const link = $("#expeditionReportLink");
  link.href = `/api/inspection/reports/${encodeURIComponent(report.id)}/report.html`;
  link.hidden = false;
  $("#expeditionStatus").textContent = `HTML report ready · AI ${report.ai.status}. DA3 reconstruction continues on the PC.`;
  await refreshInspectionReports();
}

async function watchExpeditionDa3(capture) {
  clearInterval(expedition.remoteTimer);
  let polls = 0;
  expedition.remoteTimer = setInterval(async () => {
    if (++polls > 240) { clearInterval(expedition.remoteTimer); $("#expeditionStatus").textContent = "DA3 is still processing. Check its status from Reports later."; return; }
    try {
      const job = await api(`/api/remote/da3/status/${encodeURIComponent(capture)}`);
      if (job.state === "complete" && job.model_url) {
        clearInterval(expedition.remoteTimer);
        if (expedition.reportId) {
          await api(`/api/inspection/reports/${encodeURIComponent(expedition.reportId)}/attach-model`, { method: "POST" });
          $("#expeditionStatus").textContent = "DA3 GLB added to the HTML report. Reopen it to view the model.";
        }
      } else if (job.state === "failed") {
        clearInterval(expedition.remoteTimer);
        $("#expeditionStatus").textContent = `DA3 failed: ${job.error || "unknown error"}. The report remains available.`;
      }
    } catch (error) { $("#expeditionStatus").textContent = `Checking DA3: ${error.message}`; }
  }, 5000);
}

async function stopExpedition() {
  const button = $("#expeditionStop"); button.disabled = true;
  await stopRoverDrive(true);
  $("#expeditionStatus").textContent = "Saving video, sensor samples and LiDAR map…";
  const capture = expedition.capture;
  try {
    if (state.live.recording) await api("/api/live/record/stop", { method: "POST" });
    const saved = await api("/api/expedition/map/save", { method: "POST" });
    expedition.roomId = saved.room_id || expedition.roomId;
    try { await api("/api/expedition/lidar/stop", { method: "POST" }); } catch { /* Map is already saved. */ }
    expedition.capture = null;
    $("#expeditionStart").disabled = false;
    if (!expedition.roomId) throw new Error("LiDAR room ID was not returned. The capture is saved; choose a room on Reports.");
    $("#expeditionStatus").textContent = "Generating HTML report and sending frames to the DA3 PC…";
    const [report, transfer] = await Promise.allSettled([
      finishExpeditionReport(capture, expedition.roomId),
      api(`/api/remote/da3/send/${encodeURIComponent(capture)}`, { method: "POST" }),
    ]);
    if (report.status === "rejected") $("#expeditionStatus").textContent = `Report failed: ${report.reason.message}. Capture ${capture} is saved.`;
    if (transfer.status === "fulfilled") watchExpeditionDa3(capture);
    else $("#expeditionStatus").textContent += ` DA3 transfer: ${transfer.reason.message}. Configure Tailscale on Setup/Reports and retry there.`;
    await refreshLiveStatus(false);
  } catch (error) {
    try { await api("/api/expedition/lidar/stop", { method: "POST" }); } catch { /* Preserve the original error. */ }
    expedition.capture = null;
    $("#expeditionStatus").textContent = `${error.message} Capture ${capture || ""} is retained.`;
    $("#expeditionStart").disabled = false;
    toast("Expedition stop needs attention", error.message, "error");
  }
}

async function refreshAll() {
  await Promise.allSettled([
    refreshHealth(), refreshModels(), refreshLiveStatus(false), refreshRoverStatus(), refreshGamepadStatus(), refreshAutonomyStatus(), refreshSensors(), refreshCaptures(), refreshRuns(), refreshJobs(), refreshInspectionReports(), window.PitMission?.refresh?.(),
  ]);
}

function updateClock() {
  $("#clock").textContent = new Intl.DateTimeFormat(undefined, {
    weekday: "short", hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).format(new Date());
  updateRecordingTimer();
}

async function initialize() {
  $("#setupDa3Save").addEventListener("click", async () => {
    const button = $("#setupDa3Save"); button.disabled = true;
    try {
      const config = await api("/api/remote/da3/config", { method: "POST", body: {
        url: $("#setupDa3Url").value.trim(), token: $("#setupDa3Token").value,
      }});
      $("#setupDa3Token").value = "";
      $("#setupDa3Status").textContent = `DA3 PC configured: ${config.url}.`;
    } catch (error) { $("#setupDa3Status").textContent = error.message; }
    finally { button.disabled = false; }
  });
  try {
    const config = await api("/api/remote/da3/config");
    if (config.configured) { $("#setupDa3Url").value = config.url; $("#setupDa3Status").textContent = `DA3 PC configured: ${config.url}.`; }
  } catch { /* Setup can continue without the remote PC. */ }
  $("#setupCameraSave").addEventListener("click", () => {
    const url = $("#setupCameraUrl").value.trim();
    if (!/^https?:\/\/[^\s]+$/i.test(url)) return toast("Invalid camera URL", "Enter the camera stream URL including http://", "error");
    $("#streamUrl").value = url;
    localStorage.setItem("pitdivers.cameraUrl", url);
    $("#setupCameraStatus").textContent = `Saved ${url}. Connect the stream on Live.`;
  });
  $("#setupWheelUrl").value = localStorage.getItem("pitdivers.roverUrl") || $("#roverUrl").value;
  $("#setupSensorUrl").value = localStorage.getItem("pitdivers.sensorUrl") || "http://192.168.0.99";
  $("#setupWheelSave").addEventListener("click", () => {
    const url = $("#setupWheelUrl").value.trim().replace(/\/$/, "");
    if (!/^https?:\/\/[^\s/]+$/i.test(url)) return toast("Invalid wheel URL", "Enter the ESP base address including http://", "error");
    $("#roverUrl").value = url;
    localStorage.setItem("pitdivers.roverUrl", url);
    $("#setupWheelStatus").textContent = `Saved ${url}. Connect controls on Drive.`;
  });
  $("#setupSensorSave").addEventListener("click", () => {
    const url = $("#setupSensorUrl").value.trim().replace(/\/$/, "");
    if (!/^https?:\/\/[^\s/]+$/i.test(url)) return toast("Invalid sensor URL", "Enter the ESP base address including http://", "error");
    $("#setupSensorUrl").value = url;
    localStorage.setItem("pitdivers.sensorUrl", url);
    $("#setupSensorStatus").textContent = `Saved ${url}. Reconnect the camera if it is running.`;
    refreshSensors();
  });
  $("#createReportButton").addEventListener("click", createInspectionReport);
  $("#inspectionConfigureCamera").addEventListener("click", () => setTab("live"));
  $("#inspectionRecordButton").addEventListener("click", toggleRecording);
  $("#sendDa3Button").addEventListener("click", sendCaptureToDa3);
  $("#checkDa3Button").addEventListener("click", checkRemoteDa3);
  const imuPanel = $(".env-grid > .imu-card");
  const imuDialogBody = $("#imuDialogBody");
  if (imuPanel && imuDialogBody) imuDialogBody.append(imuPanel);
  const storedCameraUrl = localStorage.getItem("pitdivers.cameraUrl");
  $("#streamUrl").value = !storedCameraUrl || storedCameraUrl === "http://192.168.0.69/jpg"
    ? "http://192.168.0.119/jpg"
    : storedCameraUrl;
  $("#setupCameraUrl").value = $("#streamUrl").value;
  $("#roverUrl").value = localStorage.getItem("pitdivers.roverUrl") || $("#roverUrl").value;
  $("#setupWheelUrl").value = $("#roverUrl").value;
  try {
    const visibility = JSON.parse(localStorage.getItem("pitdivers.feedVisibility") || "{}");
    if (typeof visibility.raw === "boolean") $("#showRawFeed").checked = visibility.raw;
    if (typeof visibility.depth === "boolean") $("#showDepthFeed").checked = visibility.depth;
    if (typeof visibility.semantic === "boolean") $("#showSemanticFeed").checked = visibility.semantic;
  } catch { /* Ignore invalid saved display preferences. */ }
  applyFeedVisibility();
  $("#lowLightMode").value = localStorage.getItem("pitdivers.lowLightMode") || $("#lowLightMode").value;
  $("#lowLightStrength").value = localStorage.getItem("pitdivers.lowLightStrength") || $("#lowLightStrength").value;
  $("#lowLightStrengthValue").textContent = `${$("#lowLightStrength").value}%`;
  syncAutonomyMission();
  renderRoverStatus();
  await window.PitMission?.init?.();
  bindEvents();
  $("#captureName").value = createCaptureName();
  updateClock();
  setInterval(updateClock, 1000);
  window.addEventListener("resize", () => window.requestAnimationFrame(drawSensorCharts));
  drawSensorCharts();
  await refreshAll();
  await refreshOllamaModels();
  setInterval(() => refreshLiveStatus(), 1000);
  setInterval(() => refreshRoverStatus(), 1500);
  setInterval(() => { refreshGamepadStatus(); refreshAutonomyStatus(); }, 1000);
  window.setTimeout(pollSensors, SENSOR_POLL_INTERVAL_MS);
  setInterval(() => refreshFilmstrip(), 800);
  setInterval(() => refreshJobs(), 1200);
  setInterval(() => { refreshCaptures(); refreshRuns(); refreshModels(); }, 6000);
  setInterval(refreshExpeditionMap, 2000);
}

initialize();
