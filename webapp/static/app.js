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
};

const MAX_SENSOR_POINTS = 240;

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
    $("#temperatureValue").textContent = `${sensor.temperature_c.toFixed(1)} °C`;
    $("#humidityValue").textContent = `${sensor.humidity_percent.toFixed(1)}%`;
    $("#sensorPinLabel").textContent = `DHT11 · GPIO ${sensor.gpio}`;
    $("#sensorStatus").textContent = "DHT11 online";
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
    $("#temperatureValue").textContent = "—";
    $("#humidityValue").textContent = "—";
    $("#sensorStatus").textContent = "Sensor offline";
    drawSensorCharts();
  }
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

function drawSensorChart(canvasId, valueKey, color, unit) {
  const canvas = $(`#${canvasId}`);
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

  const padding = { left: 47, right: 13, top: 15, bottom: 28 };
  const plotWidth = Math.max(1, bounds.width - padding.left - padding.right);
  const plotHeight = Math.max(1, bounds.height - padding.top - padding.bottom);
  const points = state.sensorHistory;

  context.lineWidth = 1;
  context.strokeStyle = "rgba(137, 150, 163, 0.14)";
  for (let index = 0; index <= 4; index += 1) {
    const y = padding.top + (plotHeight * index) / 4;
    context.beginPath();
    context.moveTo(padding.left, y);
    context.lineTo(padding.left + plotWidth, y);
    context.stroke();
  }
  for (let index = 0; index <= 6; index += 1) {
    const x = padding.left + (plotWidth * index) / 6;
    context.beginPath();
    context.moveTo(x, padding.top);
    context.lineTo(x, padding.top + plotHeight);
    context.stroke();
  }

  context.font = "9px Inter, ui-sans-serif, system-ui, sans-serif";
  context.fillStyle = "#687580";
  if (!points.length) {
    context.textAlign = "center";
    context.fillText("Waiting for DHT11 readings…", padding.left + plotWidth / 2, padding.top + plotHeight / 2);
    return;
  }

  const values = points.map((point) => point[valueKey]);
  const [minimum, maximum] = chartBounds(values, valueKey);
  const range = maximum - minimum || 1;
  const firstTime = points[0].time;
  const lastTime = points.at(-1).time;
  const displayedWindowMs = Math.max(600000, lastTime - firstTime);
  const windowStart = lastTime - displayedWindowMs;
  const xFor = (time) => padding.left + ((time - windowStart) / displayedWindowMs) * plotWidth;
  const yFor = (value) => padding.top + ((maximum - value) / range) * plotHeight;

  context.textAlign = "right";
  context.textBaseline = "middle";
  for (let index = 0; index <= 4; index += 1) {
    const value = maximum - (range * index) / 4;
    context.fillText(`${value.toFixed(valueKey === "humidity" ? 0 : 1)}${unit}`, padding.left - 7, padding.top + (plotHeight * index) / 4);
  }

  const timeFormat = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  context.textBaseline = "alphabetic";
  context.textAlign = "left";
  context.fillText(timeFormat.format(new Date(windowStart)), padding.left, bounds.height - 7);
  context.textAlign = "right";
  context.fillText(timeFormat.format(new Date(lastTime)), padding.left + plotWidth, bounds.height - 7);

  const gradient = context.createLinearGradient(0, padding.top, 0, padding.top + plotHeight);
  gradient.addColorStop(0, `${color}38`);
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

  context.beginPath();
  points.forEach((point, index) => {
    const x = xFor(point.time);
    const y = yFor(point[valueKey]);
    if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
  });
  context.strokeStyle = color;
  context.lineWidth = 2;
  context.lineJoin = "round";
  context.lineCap = "round";
  context.shadowColor = `${color}66`;
  context.shadowBlur = 8;
  context.stroke();
  context.shadowBlur = 0;

  const lastPoint = points.at(-1);
  context.beginPath();
  context.arc(xFor(lastPoint.time), yFor(lastPoint[valueKey]), 3.5, 0, Math.PI * 2);
  context.fillStyle = color;
  context.fill();
}

function drawSensorCharts() {
  drawSensorChart("temperatureChart", "temperature", "#ff7433", "°");
  drawSensorChart("humidityChart", "humidity", "#29d3c2", "%");

  if (!state.sensorHistory.length) return;
  const temperatures = state.sensorHistory.map((point) => point.temperature);
  const humidities = state.sensorHistory.map((point) => point.humidity);
  $("#temperatureRange").textContent = `${Math.min(...temperatures).toFixed(1)}–${Math.max(...temperatures).toFixed(1)} °C`;
  $("#humidityRange").textContent = `${Math.min(...humidities).toFixed(1)}–${Math.max(...humidities).toFixed(1)}% RH`;
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
    const frameButton = event.target.closest("[data-photo-url]");
    if (photoButton) openPhotos(photoButton.dataset.openPhotos);
    if (reconstructButton) openReconstruct(reconstructButton.dataset.reconstruct);
    if (viewerButton) openViewer(viewerButton.dataset.viewRun);
    if (downloadButton) downloadModel(downloadButton.dataset.downloadModel);
    if (cancelButton) cancelJob(cancelButton.dataset.cancelJob);
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
  setInterval(() => refreshJobs(), 1200);
  setInterval(() => { refreshCaptures(); refreshRuns(); refreshModels(); }, 6000);
}

initialize();
