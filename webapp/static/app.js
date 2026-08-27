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
};

const MAX_SENSOR_POINTS = 1500;       // ~1 hour of history at 2.5s cadence
const MIN_WINDOW_MS = 60000;          // axis starts at a 1-minute span
const MAX_WINDOW_MS = 3600000;        // and grows to a 1-hour rolling window
const ENV_COLORS = { temperature: "#ff7433", humidity: "#29d3c2" };

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

  const recordButton = $("#recordButton");
  recordButton.disabled = !cameraReady;
  recordButton.classList.toggle("active", Boolean(live.recording));
  recordButton.innerHTML = `<span></span>${live.recording ? "Stop recording" : "Start recording"}`;
  $("#captureName").disabled = Boolean(live.recording);
  $("#keyframeFps").disabled = Boolean(live.recording);

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
    if (!sensor.ok || !Number.isFinite(sensor.temperature_c) || !Number.isFinite(sensor.humidity_percent)) {
      throw new Error(sensor.error || `DHT11 status ${sensor.status_code ?? "unknown"}`);
    }
    setEnvValue("temperature", sensor.temperature_c, "°C");
    setEnvValue("humidity", sensor.humidity_percent, "%");
    state.sensorHistory.push({
      time: Date.now(),
      temperature: sensor.temperature_c,
      humidity: sensor.humidity_percent,
    });
    if (state.sensorHistory.length > MAX_SENSOR_POINTS) {
      state.sensorHistory.splice(0, state.sensorHistory.length - MAX_SENSOR_POINTS);
    }
    drawSensorCharts();
  } catch (error) {
    setEnvOffline();
    drawSensorCharts();
  }
}

function envStatus(kind, value) {
  if (kind === "humidity") {
    if (value < 30) return { label: "Dry", tone: "#ffc65a" };
    if (value <= 60) return { label: "Moderate", tone: "#29d3c2" };
    return { label: "Humid", tone: "#5ce09a" };
  }
  if (value < 10) return { label: "Cold", tone: "#4aa8ff" };
  if (value <= 30) return { label: "Normal", tone: "#5ce09a" };
  return { label: "Hot", tone: "#ff5364" };
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

function setEnvOffline() {
  for (const kind of ["temperature", "humidity"]) {
    const valueEl = $(`#${kind}Value`);
    if (valueEl) valueEl.textContent = "—";
    const pill = $(`#${kind}Status`);
    if (pill) {
      pill.style.color = "var(--muted)";
      pill.style.background = "rgba(137,150,163,.12)";
      pill.querySelector("em").textContent = "Offline";
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

  const points = state.sensorHistory;
  const padding = { left: 12, right: 44, top: 12, bottom: 22 };
  const plotWidth = Math.max(1, bounds.width - padding.left - padding.right);
  const plotHeight = Math.max(1, bounds.height - padding.top - padding.bottom);

  if (points.length < 2) {
    context.font = "10px Inter, ui-sans-serif, system-ui, sans-serif";
    context.fillStyle = "#687580";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText("Waiting for DHT11 readings…", padding.left + plotWidth / 2, padding.top + plotHeight / 2);
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

const CHART_META = {
  temperature: { valueKey: "temperature", color: "#ff7433", unit: "°", rangeUnit: "°C", label: "Temperature history", cyan: false },
  humidity: { valueKey: "humidity", color: "#29d3c2", unit: "%", rangeUnit: "% RH", label: "Humidity history", cyan: true },
};

function sensorRange(valueKey, rangeUnit) {
  if (!state.sensorHistory.length) return "Waiting for data";
  const values = state.sensorHistory.map((point) => point[valueKey]);
  return `${Math.min(...values).toFixed(1)}–${Math.max(...values).toFixed(1)} ${rangeUnit}`;
}

function drawSensorCharts() {
  drawSensorChart($("#temperatureSpark"), { valueKey: "temperature", color: ENV_COLORS.temperature, unit: "°" });
  drawSensorChart($("#humiditySpark"), { valueKey: "humidity", color: ENV_COLORS.humidity, unit: "%" });
  if (state.openChart) {
    const meta = state.openChart;
    drawSensorChart($("#chartDialogCanvas"), { valueKey: meta.valueKey, color: meta.color, unit: meta.unit });
    $("#chartDialogRange").textContent = sensorRange(meta.valueKey, meta.rangeUnit);
  }
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
        },
      });
      toast("Recording started", `Saving keyframes to data/${result.name}`);
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
    $("#photoSummary").textContent = `${photos.length} photos • click any frame for full size`;
    $("#photoGrid").innerHTML = photos.map((photo) => `
      <button data-photo-url="${escapeHtml(photo.url)}" data-photo-name="${escapeHtml(photo.name)}" title="${escapeHtml(photo.name)}">
        <img src="${escapeHtml(photo.url)}" alt="${escapeHtml(photo.name)}" loading="lazy" />
      </button>`).join("");
  } catch (error) {
    $("#photoGrid").innerHTML = `<div class="empty-card"><div><strong>Could not load photos</strong>${escapeHtml(error.message)}</div></div>`;
  }
}

function openReconstruct(captureName) {
  const capture = state.captures.find((item) => item.name === captureName);
  $("#reconstructCapture").value = captureName;
  $("#reconstructTarget").innerHTML = `<strong>${escapeHtml(captureName)}</strong><br>${capture?.images || 0} keyframes • ${formatBytes(capture?.size_bytes || 0)}`;
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
      },
    });
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
  } catch { /* polling will retry */ }
}

function renderJobs() {
  const container = $("#activeJobs");
  const active = state.jobs.jobs.filter((job) => ["queued", "running", "cancelling", "error"].includes(job.state));
  container.innerHTML = active.map((job) => `
    <article class="job-card">
      <div class="job-top">
        <div><p class="eyebrow">${escapeHtml(job.state.toUpperCase())}</p><h3>${escapeHtml(job.capture)} → ${escapeHtml(job.run_name)}</h3><p>${escapeHtml(job.stage)} • ${job.images} images • ${escapeHtml(modelName(job.model_id))}</p></div>
        ${["queued", "running"].includes(job.state) ? `<button class="button danger" data-cancel-job="${escapeHtml(job.id)}">Stop</button>` : ""}
      </div>
      <div class="progress-track"><span style="width:${Number(job.progress || 0)}%"></span></div>
      <div class="job-foot"><span>${escapeHtml(job.error || job.stage)}</span><strong>${Number(job.progress || 0)}%</strong></div>
      ${job.logs?.length ? `<div class="job-logs">${escapeHtml(job.logs.slice(-8).join("\n"))}</div>` : ""}
    </article>`).join("");
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
          <a class="button secondary" href="${escapeHtml(run.download_url)}">Download</a>
        </div>
      </div>
    </article>`).join("");
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
  dialog.close();
}

function bindEvents() {
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => setTab(button.dataset.tab)));
  $("#connectButton").addEventListener("click", toggleConnection);
  $("#recordButton").addEventListener("click", toggleRecording);
  $("#refreshButton").addEventListener("click", refreshAll);
  $("#reconstructForm").addEventListener("submit", submitReconstruction);
  $$('[data-go-live]').forEach((button) => button.addEventListener("click", () => setTab("live")));
  $$('[data-go-captures]').forEach((button) => button.addEventListener("click", () => setTab("captures")));

  document.addEventListener("click", (event) => {
    const photoButton = event.target.closest("[data-open-photos]");
    const reconstructButton = event.target.closest("[data-reconstruct]");
    const viewerButton = event.target.closest("[data-view-run]");
    const downloadButton = event.target.closest("[data-download-model]");
    const cancelButton = event.target.closest("[data-cancel-job]");
    const popChartButton = event.target.closest("[data-pop-chart]");
    const frameButton = event.target.closest("[data-photo-url]");
    if (photoButton) openPhotos(photoButton.dataset.openPhotos);
    if (reconstructButton) openReconstruct(reconstructButton.dataset.reconstruct);
    if (viewerButton) openViewer(viewerButton.dataset.viewRun);
    if (downloadButton) downloadModel(downloadButton.dataset.downloadModel);
    if (cancelButton) cancelJob(cancelButton.dataset.cancelJob);
    if (popChartButton) openChartPopout(popChartButton.dataset.popChart);
    if (frameButton) {
      $("#lightboxImage").src = frameButton.dataset.photoUrl;
      $("#lightboxLabel").textContent = frameButton.dataset.photoName;
      $("#lightbox").hidden = false;
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
  bindEvents();
  $("#captureName").value = createCaptureName();
  updateClock();
  setInterval(updateClock, 1000);
  window.addEventListener("resize", () => window.requestAnimationFrame(drawSensorCharts));
  drawSensorCharts();
  await refreshAll();
  setInterval(() => refreshLiveStatus(), 1000);
  setInterval(() => refreshSensors(), 2500);
  setInterval(() => refreshFilmstrip(), 800);
  setInterval(() => refreshJobs(), 1200);
  setInterval(() => { refreshCaptures(); refreshRuns(); refreshModels(); }, 6000);
}

initialize();
