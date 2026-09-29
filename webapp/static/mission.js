(function () {
  "use strict";

  const mission = {
    initialized: false,
    loadedOnce: false,
    maps: [],
    map: null,
    tool: "select",
    selectedWaypoint: null,
    draft: [],
    draftType: null,
    dragging: false,
    dirty: false,
    validation: null,
    plan: null,
    simulation: { running: false, token: 0, position: null, command: null },
    transform: null,
  };

  const actionLabels = {
    take_photo: "Take photo",
    temperature: "Read temperature",
    humidity: "Read humidity",
    distance_scan: "Distance scan",
    vibration_scan: "Vibration scan",
    wait: "Wait",
    return_home: "Return home",
  };

  const el = (selector) => document.querySelector(selector);
  const all = (selector) => [...document.querySelectorAll(selector)];
  const uid = (prefix) => `${prefix}-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const number = (value, fallback) => Number.isFinite(Number(value)) ? Number(value) : fallback;

  function freshMap() {
    return {
      schema_version: 1,
      id: "",
      name: "Untitled mission",
      frame_id: "map",
      units: "metres",
      width_m: 10,
      height_m: 8,
      grid_m: 0.5,
      rover_radius_m: 0.18,
      boundary: [{ x: 0.5, y: 0.5 }, { x: 9.5, y: 0.5 }, { x: 9.5, y: 7.5 }, { x: 0.5, y: 7.5 }],
      obstacles: [],
      teach_trace: [],
      route: [],
      source_capture: null,
      created_at: null,
      updated_at: null,
      metadata: {},
    };
  }

  function notify(title, message = "", kind = "info") {
    if (typeof window.toast === "function") {
      window.toast(title, message, kind);
      return;
    }
    console[kind === "error" ? "error" : "log"](title, message);
  }

  async function request(path, options = {}) {
    const init = { ...options, headers: { ...(options.headers || {}) } };
    if (init.body && typeof init.body !== "string") {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(init.body);
    }
    const response = await fetch(path, init);
    let body = null;
    try { body = await response.json(); } catch { /* no body */ }
    if (!response.ok) throw new Error(body?.detail || body?.error || `Request failed (${response.status})`);
    return body;
  }

  function syncMapFromForm() {
    if (!mission.map) return;
    mission.map.name = el("#mapName").value.trim() || "Untitled mission";
    mission.map.width_m = clamp(number(el("#mapWidth").value, 10), 1, 10000);
    mission.map.height_m = clamp(number(el("#mapHeight").value, 8), 1, 10000);
    mission.map.grid_m = clamp(number(el("#mapGrid").value, 0.5), 0.1, 100);
    mission.map.rover_radius_m = clamp(number(el("#roverRadius").value, 0.18), 0.05, 5);
    el("#canvasMissionName").textContent = mission.map.name;
  }

  function syncFormFromMap() {
    const map = mission.map;
    el("#mapName").value = map.name;
    el("#mapWidth").value = map.width_m;
    el("#mapHeight").value = map.height_m;
    el("#mapGrid").value = map.grid_m;
    el("#roverRadius").value = map.rover_radius_m;
    el("#canvasMissionName").textContent = map.name;
    el("#mapFrameLabel").textContent = `${String(map.frame_id || "map").toUpperCase()} FRAME`;
    renderWaypointInspector();
    updateMetrics();
  }

  function markDirty() {
    mission.dirty = true;
    mission.validation = null;
    mission.plan = null;
    el("#saveMapButton").textContent = "Save map •";
    renderValidation();
    updateMetrics();
    draw();
  }

  function setTool(tool) {
    mission.tool = tool;
    mission.draft = [];
    mission.draftType = null;
    mission.dragging = false;
    all("[data-map-tool]").forEach((button) => button.classList.toggle("active", button.dataset.mapTool === tool));
    el("#mapToolReadout").textContent = tool.toUpperCase();
    el("#missionCanvas").style.cursor = tool === "select" ? "default" : "crosshair";
    draw();
  }

  function canvasTransform() {
    const canvas = el("#missionCanvas");
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(320, rect.width);
    const height = Math.max(300, rect.height);
    const margin = 38;
    const scale = Math.min((width - margin * 2) / mission.map.width_m, (height - margin * 2) / mission.map.height_m);
    const mapWidth = mission.map.width_m * scale;
    const mapHeight = mission.map.height_m * scale;
    return { width, height, scale, left: (width - mapWidth) / 2, bottom: (height - mapHeight) / 2 };
  }

  function toCanvas(point) {
    const t = mission.transform;
    return { x: t.left + point.x * t.scale, y: t.height - t.bottom - point.y * t.scale };
  }

  function toWorld(event) {
    const rect = el("#missionCanvas").getBoundingClientRect();
    const t = mission.transform;
    return {
      x: clamp((event.clientX - rect.left - t.left) / t.scale, 0, mission.map.width_m),
      y: clamp((t.height - t.bottom - (event.clientY - rect.top)) / t.scale, 0, mission.map.height_m),
    };
  }

  function drawPolyline(ctx, points, color, width, close = false, fill = null, dash = []) {
    if (!points.length) return;
    ctx.save();
    ctx.beginPath();
    const first = toCanvas(points[0]);
    ctx.moveTo(first.x, first.y);
    points.slice(1).forEach((point) => {
      const pixel = toCanvas(point);
      ctx.lineTo(pixel.x, pixel.y);
    });
    if (close) ctx.closePath();
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.setLineDash(dash);
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();
    ctx.restore();
  }

  function draw() {
    if (!mission.initialized || !mission.map) return;
    const canvas = el("#missionCanvas");
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(rect.width * dpr) || canvas.height !== Math.round(rect.height * dpr)) {
      canvas.width = Math.round(rect.width * dpr);
      canvas.height = Math.round(rect.height * dpr);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    mission.transform = canvasTransform();
    const t = mission.transform;
    ctx.clearRect(0, 0, t.width, t.height);
    ctx.fillStyle = "#080c10";
    ctx.fillRect(0, 0, t.width, t.height);

    const top = t.height - t.bottom - mission.map.height_m * t.scale;
    const right = t.left + mission.map.width_m * t.scale;
    ctx.fillStyle = "#0b1116";
    ctx.fillRect(t.left, top, right - t.left, mission.map.height_m * t.scale);

    const grid = Math.max(0.01, mission.map.grid_m);
    const maxLines = 250;
    const step = Math.max(grid, Math.ceil(Math.max(mission.map.width_m, mission.map.height_m) / maxLines / grid) * grid);
    ctx.save();
    ctx.strokeStyle = "rgba(112, 132, 147, .13)";
    ctx.lineWidth = 1;
    ctx.fillStyle = "#52606b";
    ctx.font = "9px ui-monospace, Consolas, monospace";
    for (let x = 0; x <= mission.map.width_m + 1e-8; x += step) {
      const p = toCanvas({ x, y: 0 });
      ctx.beginPath(); ctx.moveTo(p.x, top); ctx.lineTo(p.x, t.height - t.bottom); ctx.stroke();
      if (Math.round(x / step) % 2 === 0) ctx.fillText(`${x.toFixed(step < 1 ? 1 : 0)}m`, p.x + 3, t.height - t.bottom + 15);
    }
    for (let y = 0; y <= mission.map.height_m + 1e-8; y += step) {
      const p = toCanvas({ x: 0, y });
      ctx.beginPath(); ctx.moveTo(t.left, p.y); ctx.lineTo(right, p.y); ctx.stroke();
      if (y > 0 && Math.round(y / step) % 2 === 0) ctx.fillText(`${y.toFixed(step < 1 ? 1 : 0)}`, t.left - 28, p.y + 3);
    }
    ctx.restore();

    drawPolyline(ctx, mission.map.boundary, "#29d3c2", 2, true, "rgba(41, 211, 194, .035)", [7, 5]);
    mission.map.obstacles.forEach((obstacle) => drawPolyline(ctx, obstacle.polygon, "#ff5364", 2, true, "rgba(255, 83, 100, .15)"));
    drawPolyline(ctx, mission.map.teach_trace, "rgba(168, 120, 255, .8)", 2, false, null, [3, 5]);

    if (mission.map.route.length > 1) {
      drawPolyline(ctx, mission.map.route, "#ff7433", 4, false, null);
      for (let index = 1; index < mission.map.route.length; index += 1) {
        const from = toCanvas(mission.map.route[index - 1]);
        const to = toCanvas(mission.map.route[index]);
        const angle = Math.atan2(to.y - from.y, to.x - from.x);
        const x = from.x + (to.x - from.x) * 0.58;
        const y = from.y + (to.y - from.y) * 0.58;
        ctx.save(); ctx.translate(x, y); ctx.rotate(angle); ctx.fillStyle = "#ffb07f";
        ctx.beginPath(); ctx.moveTo(7, 0); ctx.lineTo(-5, -4); ctx.lineTo(-5, 4); ctx.closePath(); ctx.fill(); ctx.restore();
      }
    }

    mission.map.route.forEach((waypoint, index) => {
      const p = toCanvas(waypoint);
      const selected = waypoint.id === mission.selectedWaypoint;
      ctx.beginPath(); ctx.arc(p.x, p.y, selected ? 10 : 8, 0, Math.PI * 2);
      ctx.fillStyle = selected ? "#fff" : index === 0 ? "#5ce09a" : "#ff7433"; ctx.fill();
      ctx.lineWidth = selected ? 4 : 2; ctx.strokeStyle = selected ? "rgba(255,116,51,.6)" : "#090d11"; ctx.stroke();
      ctx.fillStyle = selected ? "#10151a" : "#fff"; ctx.font = "bold 8px Inter, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(String(index + 1), p.x, p.y + 0.5);
      if (waypoint.actions.length) {
        ctx.fillStyle = "#ffc65a"; ctx.beginPath(); ctx.arc(p.x + 9, p.y - 9, 4, 0, Math.PI * 2); ctx.fill();
      }
    });

    if (mission.draft.length) {
      drawPolyline(ctx, mission.draft, mission.draftType === "obstacle" ? "#ff5364" : "#29d3c2", 2, false, null, [4, 4]);
      mission.draft.forEach((point) => { const p = toCanvas(point); ctx.fillStyle = "#fff"; ctx.fillRect(p.x - 3, p.y - 3, 6, 6); });
    }

    if (mission.simulation.position) {
      const p = toCanvas(mission.simulation.position);
      const yaw = number(mission.simulation.position.yaw_deg, 0) * Math.PI / 180;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(-yaw); ctx.shadowColor = "#5ce09a"; ctx.shadowBlur = 15;
      ctx.fillStyle = "#5ce09a"; ctx.strokeStyle = "#07100b"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(12, 0); ctx.lineTo(-8, -8); ctx.lineTo(-5, 0); ctx.lineTo(-8, 8); ctx.closePath(); ctx.fill(); ctx.stroke(); ctx.restore();
    }
    el("#mapEmptyHint").hidden = mission.map.route.length > 0;
  }

  function hitWaypoint(world, radiusPixels = 15) {
    let best = null;
    let bestDistance = Infinity;
    mission.map.route.forEach((waypoint) => {
      const distance = Math.hypot(waypoint.x - world.x, waypoint.y - world.y) * mission.transform.scale;
      if (distance <= radiusPixels && distance < bestDistance) { best = waypoint; bestDistance = distance; }
    });
    return best;
  }

  function addRoutePoint(point) {
    const index = mission.map.route.length + 1;
    const waypoint = { id: uid("wp"), name: index === 1 ? "Home" : `Waypoint ${index}`, x: point.x, y: point.y, heading_deg: null, speed_mps: 0.3, tolerance_m: 0.2, actions: [] };
    mission.map.route.push(waypoint);
    mission.selectedWaypoint = waypoint.id;
    renderWaypointInspector();
    markDirty();
  }

  function finishShape() {
    if (!mission.draftType || !mission.draft.length) return;
    if (mission.draft.length < 3) {
      notify("Shape needs more points", "Add at least three vertices.", "error");
      return;
    }
    if (mission.draftType === "boundary") mission.map.boundary = [...mission.draft];
    if (mission.draftType === "obstacle") {
      const count = mission.map.obstacles.length + 1;
      mission.map.obstacles.push({ id: uid("obstacle"), name: `Obstacle ${count}`, polygon: [...mission.draft] });
    }
    mission.draft = [];
    mission.draftType = null;
    markDirty();
  }

  function onCanvasPointerDown(event) {
    if (event.button !== 0) return;
    const point = toWorld(event);
    if (mission.tool === "route") return addRoutePoint(point);
    if (mission.tool === "boundary" || mission.tool === "obstacle") {
      mission.draftType = mission.tool;
      mission.draft.push(point);
      draw();
      return;
    }
    const hit = hitWaypoint(point);
    mission.selectedWaypoint = hit?.id || null;
    mission.dragging = Boolean(hit);
    renderWaypointInspector();
    draw();
    if (hit) event.currentTarget.setPointerCapture(event.pointerId);
  }

  function onCanvasPointerMove(event) {
    const point = toWorld(event);
    el("#mapCursorReadout").textContent = `x ${point.x.toFixed(2)} m · y ${point.y.toFixed(2)} m`;
    if (!mission.dragging || !mission.selectedWaypoint) return;
    const waypoint = mission.map.route.find((item) => item.id === mission.selectedWaypoint);
    if (!waypoint) return;
    waypoint.x = point.x; waypoint.y = point.y;
    syncWaypointFields(waypoint);
    markDirty();
  }

  function renderWaypointInspector() {
    const waypoint = mission.map?.route.find((item) => item.id === mission.selectedWaypoint);
    el("#waypointEmpty").hidden = Boolean(waypoint);
    el("#waypointFields").hidden = !waypoint;
    if (!waypoint) return;
    syncWaypointFields(waypoint);
    el("#waypointActions").innerHTML = waypoint.actions.length
      ? waypoint.actions.map((action, index) => `<button type="button" data-remove-action="${index}" title="Remove action">${actionLabels[action.type] || action.type}${action.duration_s ? ` · ${action.duration_s}s` : ""}<span>×</span></button>`).join("")
      : '<small>No actions at this waypoint.</small>';
  }

  function syncWaypointFields(waypoint) {
    el("#waypointName").value = waypoint.name;
    el("#waypointX").value = waypoint.x.toFixed(2);
    el("#waypointY").value = waypoint.y.toFixed(2);
    el("#waypointSpeed").value = waypoint.speed_mps;
    el("#waypointTolerance").value = waypoint.tolerance_m;
    el("#waypointHeading").value = waypoint.heading_deg ?? "";
  }

  function updateSelectedWaypoint() {
    const waypoint = mission.map.route.find((item) => item.id === mission.selectedWaypoint);
    if (!waypoint) return;
    waypoint.name = el("#waypointName").value.trim() || waypoint.name;
    waypoint.x = clamp(number(el("#waypointX").value, waypoint.x), 0, mission.map.width_m);
    waypoint.y = clamp(number(el("#waypointY").value, waypoint.y), 0, mission.map.height_m);
    waypoint.speed_mps = clamp(number(el("#waypointSpeed").value, waypoint.speed_mps), 0.01, 3);
    waypoint.tolerance_m = clamp(number(el("#waypointTolerance").value, waypoint.tolerance_m), 0.01, 2);
    waypoint.heading_deg = el("#waypointHeading").value === "" ? null : number(el("#waypointHeading").value, null);
    markDirty();
  }

  function deleteSelectedWaypoint() {
    if (!mission.selectedWaypoint) return;
    mission.map.route = mission.map.route.filter((item) => item.id !== mission.selectedWaypoint);
    mission.selectedWaypoint = null;
    renderWaypointInspector();
    markDirty();
  }

  function addAction() {
    const waypoint = mission.map.route.find((item) => item.id === mission.selectedWaypoint);
    if (!waypoint) return notify("Select a waypoint", "Choose where this action should run.", "error");
    const type = el("#waypointAction").value;
    let duration = clamp(number(el("#actionDuration").value, 0), 0, 3600);
    if ((type === "wait" || type === "vibration_scan") && duration === 0) duration = type === "wait" ? 5 : 10;
    waypoint.actions.push({ type, duration_s: duration, parameters: {} });
    renderWaypointInspector();
    markDirty();
  }

  function updateMetrics(report = null) {
    if (!mission.map) return;
    let distance = 0;
    for (let index = 1; index < mission.map.route.length; index += 1) {
      distance += Math.hypot(mission.map.route[index].x - mission.map.route[index - 1].x, mission.map.route[index].y - mission.map.route[index - 1].y);
    }
    el("#missionDistance").textContent = `${(report?.metrics?.route_length_m ?? distance).toFixed(2)} m`;
    el("#missionWaypointCount").textContent = String(mission.map.route.length);
    el("#missionActionCount").textContent = String(mission.map.route.reduce((total, item) => total + item.actions.length, 0));
    el("#missionTeachCount").textContent = String(mission.map.teach_trace.length);
  }

  function renderValidation() {
    const box = el("#missionValidation");
    const title = el("#missionValidationTitle");
    const list = el("#missionValidationMessages");
    box.className = "mission-validation waiting";
    if (!mission.validation) {
      title.textContent = "NOT CHECKED";
      list.innerHTML = "<li>Validate before compiling a rover plan.</li>";
      return;
    }
    const report = mission.validation;
    box.className = `mission-validation ${report.valid ? "valid" : "invalid"}`;
    title.textContent = report.valid ? "ROUTE READY" : `${report.errors.length} SAFETY ISSUE${report.errors.length === 1 ? "" : "S"}`;
    const messages = [...report.errors, ...report.warnings];
    list.innerHTML = messages.length ? messages.map((message) => `<li>${escapeText(message)}</li>`).join("") : "<li>Boundary, obstacles, and route checks passed.</li>";
    updateMetrics(report);
  }

  function escapeText(value) {
    const node = document.createElement("span"); node.textContent = String(value); return node.innerHTML;
  }

  async function validateMission(silent = false) {
    syncMapFromForm();
    try {
      mission.validation = await request("/api/maps/validate", { method: "POST", body: mission.map });
      renderValidation();
      if (!silent) notify(mission.validation.valid ? "Route ready" : "Route needs attention", mission.validation.valid ? "Safety checks passed." : mission.validation.errors[0], mission.validation.valid ? "info" : "error");
      return mission.validation;
    } catch (error) {
      notify("Validation failed", error.message, "error");
      return null;
    }
  }

  async function refreshMaps(selectedId = mission.map?.id) {
    try {
      mission.maps = await request("/api/maps");
      const picker = el("#mapPicker");
      picker.innerHTML = '<option value="">Unsaved map</option>' + mission.maps.map((item) => `<option value="${escapeText(item.id)}">${escapeText(item.name)}</option>`).join("");
      picker.value = selectedId || "";
      el("#mapBadge").textContent = String(mission.maps.length);
    } catch (error) { notify("Could not list maps", error.message, "error"); }
  }

  async function loadMap(mapId) {
    if (!mapId) return newMap();
    try {
      mission.map = await request(`/api/maps/${encodeURIComponent(mapId)}`);
      mission.selectedWaypoint = null; mission.dirty = false; mission.validation = null; mission.plan = null;
      el("#saveMapButton").textContent = "Save map";
      syncFormFromMap(); renderValidation(); draw();
    } catch (error) { notify("Could not load map", error.message, "error"); }
  }

  function newMap() {
    stopSimulation();
    mission.map = freshMap(); mission.selectedWaypoint = null; mission.dirty = true; mission.validation = null; mission.plan = null;
    el("#mapPicker").value = ""; el("#saveMapButton").textContent = "Save map •";
    syncFormFromMap(); renderValidation(); draw();
  }

  async function saveMap() {
    syncMapFromForm();
    try {
      const id = mission.map.id;
      const result = await request(id ? `/api/maps/${encodeURIComponent(id)}` : "/api/maps", { method: id ? "PUT" : "POST", body: mission.map });
      mission.map = result.map; mission.validation = result.validation; mission.dirty = false;
      el("#saveMapButton").textContent = "Save map";
      syncFormFromMap(); renderValidation(); await refreshMaps(mission.map.id);
      notify("Mission map saved", `${mission.map.name} is stored locally.`);
    } catch (error) { notify("Could not save map", error.message, "error"); }
  }

  function normalPoint(value) {
    if (Array.isArray(value)) return { x: number(value[0], 0), y: number(value[1], 0) };
    const source = value?.position || value || {};
    return { x: number(source.x, 0), y: number(source.y, 0) };
  }

  function normaliseImported(payload) {
    const raw = payload.map || payload;
    const base = freshMap();
    const teach = raw.teach_trace || raw.poses || raw.trajectory || [];
    const route = raw.route || [];
    const obstacles = raw.obstacles || [];
    return {
      ...base, ...raw, id: "", created_at: null, updated_at: null,
      boundary: (raw.boundary || base.boundary).map(normalPoint),
      teach_trace: teach.map((pose) => ({ ...normalPoint(pose), yaw_deg: number(pose.yaw_deg ?? pose.yaw, 0), timestamp_s: pose.timestamp_s ?? pose.time ?? null, confidence: clamp(number(pose.confidence, 1), 0, 1) })),
      obstacles: obstacles.map((item, index) => ({ id: item.id || uid("obstacle"), name: item.name || `Obstacle ${index + 1}`, polygon: (item.polygon || item.points || []).map(normalPoint) })),
      route: route.map((item, index) => ({ id: item.id || uid("wp"), name: item.name || (index ? `Waypoint ${index + 1}` : "Home"), ...normalPoint(item), heading_deg: item.heading_deg ?? null, speed_mps: number(item.speed_mps ?? item.speed, 0.3), tolerance_m: number(item.tolerance_m ?? item.tolerance, 0.2), actions: item.actions || (item.action ? [{ type: item.action, duration_s: 0, parameters: {} }] : []) })),
    };
  }

  async function importMap(file) {
    try {
      const payload = JSON.parse(await file.text());
      mission.map = normaliseImported(payload); mission.selectedWaypoint = null; mission.dirty = true; mission.validation = null; mission.plan = null;
      syncFormFromMap(); renderValidation(); draw();
      notify("Manual run imported", `${mission.map.teach_trace.length} teach poses and ${mission.map.route.length} waypoints loaded.`);
    } catch (error) { notify("Could not import map", error.message, "error"); }
    el("#importMapFile").value = "";
  }

  function exportJson(payload, suffix = "map") {
    syncMapFromForm();
    const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = `${mission.map.id || "pitdivers-mission"}-${suffix}.json`; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function renderPlan(plan) {
    const lines = [
      `${plan.mission_name} · ${plan.summary.route_length_m.toFixed(2)} m · ~${plan.summary.estimated_duration_s.toFixed(1)} s`,
      ...plan.commands.slice(0, 16).map((command) => command.command === "MOVE_TO"
        ? `${String(command.sequence).padStart(2, "0")}  MOVE_TO  (${command.x_m.toFixed(2)}, ${command.y_m.toFixed(2)})  ${command.speed_mps.toFixed(2)} m/s`
        : `${String(command.sequence).padStart(2, "0")}  ${command.command}${command.duration_s ? `  ${command.duration_s}s` : ""}`),
    ];
    if (plan.commands.length > 16) lines.push(`… ${plan.commands.length - 16} more commands`);
    el("#missionPlanPreview").textContent = lines.join("\n");
  }

  async function compileAndSimulate() {
    stopSimulation(false);
    const report = await validateMission(true);
    if (!report?.valid) return notify("Mission not started", report?.errors?.[0] || "Route validation failed.", "error");
    try {
      mission.plan = await request("/api/maps/plan", { method: "POST", body: mission.map });
      renderPlan(mission.plan);
      runSimulation(mission.plan);
    } catch (error) { notify("Could not compile mission", error.message, "error"); }
  }

  function wait(ms) { return new Promise((resolve) => window.setTimeout(resolve, ms)); }

  async function tweenPosition(from, to, durationMs, token) {
    const started = performance.now();
    const heading = Math.atan2(to.y - from.y, to.x - from.x) * 180 / Math.PI;
    return new Promise((resolve) => {
      function frame(now) {
        if (token !== mission.simulation.token) return resolve(false);
        const progress = clamp((now - started) / Math.max(durationMs, 1), 0, 1);
        const eased = progress < 0.5 ? 2 * progress * progress : 1 - Math.pow(-2 * progress + 2, 2) / 2;
        mission.simulation.position = { x: from.x + (to.x - from.x) * eased, y: from.y + (to.y - from.y) * eased, yaw_deg: heading };
        draw();
        if (progress < 1) requestAnimationFrame(frame); else resolve(true);
      }
      requestAnimationFrame(frame);
    });
  }

  async function runSimulation(plan) {
    const token = ++mission.simulation.token;
    mission.simulation.running = true;
    el("#simulateMissionButton").hidden = true; el("#stopSimulationButton").hidden = false;
    const status = el("#simulationStatus"); status.classList.add("running");
    let current = null;
    for (const command of plan.commands) {
      if (token !== mission.simulation.token) return;
      mission.simulation.command = command;
      if (command.command === "MOVE_TO") {
        const target = { x: command.x_m, y: command.y_m };
        status.querySelector("span").textContent = `Moving to waypoint ${command.waypoint_index + 1} · (${target.x.toFixed(2)}, ${target.y.toFixed(2)})`;
        if (!current) { current = target; mission.simulation.position = { ...target, yaw_deg: command.heading_deg || 0 }; draw(); }
        else {
          const duration = clamp(command.estimated_duration_s * 250, 350, 5000);
          if (!await tweenPosition(current, target, duration, token)) return;
          current = target;
        }
      } else {
        status.querySelector("span").textContent = `Running ${actionLabels[command.command.toLowerCase()] || command.command}`;
        await wait(clamp((command.duration_s || 1) * 200, 350, 1800));
      }
    }
    if (token !== mission.simulation.token) return;
    mission.simulation.running = false;
    status.classList.remove("running"); status.classList.add("complete"); status.querySelector("span").textContent = "Mission simulation complete";
    el("#simulateMissionButton").hidden = false; el("#stopSimulationButton").hidden = true;
    notify("Simulation complete", `${plan.summary.command_count} controller commands executed.`);
  }

  function stopSimulation(clearPosition = true) {
    mission.simulation.token += 1; mission.simulation.running = false; mission.simulation.command = null;
    if (clearPosition) mission.simulation.position = null;
    const status = el("#simulationStatus");
    if (status) { status.className = "simulation-status"; status.querySelector("span").textContent = "Rover simulator idle"; }
    if (el("#simulateMissionButton")) el("#simulateMissionButton").hidden = false;
    if (el("#stopSimulationButton")) el("#stopSimulationButton").hidden = true;
    draw();
  }

  function bind() {
    all("[data-map-tool]").forEach((button) => button.addEventListener("click", () => setTool(button.dataset.mapTool)));
    el("#finishShapeButton").addEventListener("click", finishShape);
    el("#newMapButton").addEventListener("click", newMap);
    el("#saveMapButton").addEventListener("click", saveMap);
    el("#mapPicker").addEventListener("change", (event) => loadMap(event.target.value));
    el("#importMapButton").addEventListener("click", () => el("#importMapFile").click());
    el("#importMapFile").addEventListener("change", (event) => event.target.files[0] && importMap(event.target.files[0]));
    el("#exportMapButton").addEventListener("click", () => exportJson(mission.map));
    el("#validateMissionButton").addEventListener("click", () => validateMission());
    el("#simulateMissionButton").addEventListener("click", compileAndSimulate);
    el("#stopSimulationButton").addEventListener("click", () => stopSimulation());
    el("#addActionButton").addEventListener("click", addAction);
    el("#deleteSelectionButton").addEventListener("click", deleteSelectedWaypoint);

    ["#mapName", "#mapWidth", "#mapHeight", "#mapGrid", "#roverRadius"].forEach((selector) => el(selector).addEventListener("input", () => { syncMapFromForm(); markDirty(); }));
    ["#waypointName", "#waypointX", "#waypointY", "#waypointSpeed", "#waypointTolerance", "#waypointHeading"].forEach((selector) => el(selector).addEventListener("input", updateSelectedWaypoint));
    el("#waypointActions").addEventListener("click", (event) => {
      const button = event.target.closest("[data-remove-action]");
      if (!button) return;
      const waypoint = mission.map.route.find((item) => item.id === mission.selectedWaypoint);
      if (!waypoint) return;
      waypoint.actions.splice(Number(button.dataset.removeAction), 1); renderWaypointInspector(); markDirty();
    });

    const canvas = el("#missionCanvas");
    canvas.addEventListener("pointerdown", onCanvasPointerDown);
    canvas.addEventListener("pointermove", onCanvasPointerMove);
    canvas.addEventListener("pointerup", () => { mission.dragging = false; });
    canvas.addEventListener("pointercancel", () => { mission.dragging = false; });
    canvas.addEventListener("dblclick", (event) => { if (mission.draftType) { event.preventDefault(); finishShape(); } });
    canvas.addEventListener("keydown", (event) => {
      if (event.key === "Delete" || event.key === "Backspace") { event.preventDefault(); deleteSelectedWaypoint(); }
      if (event.key === "Enter") finishShape();
      if (event.key === "Escape") { mission.draft = []; mission.draftType = null; draw(); }
    });
    window.addEventListener("resize", () => requestAnimationFrame(draw));
  }

  async function init() {
    if (mission.initialized) return;
    mission.map = freshMap(); mission.initialized = true;
    bind(); syncFormFromMap(); renderValidation(); setTool("select");
    await refreshMaps();
    draw();
  }

  async function activate() {
    if (!mission.initialized) await init();
    if (!mission.loadedOnce) {
      mission.loadedOnce = true;
      if (mission.maps.length) await loadMap(mission.maps[0].id);
    }
    requestAnimationFrame(draw);
  }

  async function addSemanticTarget(target) {
    await activate();
    if (!mission.map || mission.map.metadata?.semantic_run !== target.semantic_run) {
      mission.map = freshMap();
      mission.map.name = `Semantic inspection · ${target.semantic_run}`;
      mission.map.metadata = { semantic_run: target.semantic_run, semantic_targets: [] };
      mission.map.route = [{
        id: uid("wp"), name: "Home", x: 0.5, y: 0.5, heading_deg: null,
        speed_mps: 0.3, tolerance_m: 0.2, actions: [],
      }];
    }
    const width = Math.max(mission.map.width_m, Math.ceil(target.x + 1));
    const height = Math.max(mission.map.height_m, Math.ceil(target.y + 1));
    mission.map.width_m = width;
    mission.map.height_m = height;
    mission.map.boundary = [{x: 0.1, y: 0.1}, {x: width - 0.1, y: 0.1}, {x: width - 0.1, y: height - 0.1}, {x: 0.1, y: height - 0.1}];
    const existing = mission.map.route.find((item) => item.semantic_object_id === target.semantic_object_id);
    if (existing) {
      mission.selectedWaypoint = existing.id;
    } else {
      const waypoint = {
        id: uid("wp"), name: target.name, x: target.x, y: target.y, heading_deg: null,
        speed_mps: 0.2, tolerance_m: 0.25,
        actions: [{type: "take_photo", duration_s: 0, parameters: {semantic_run: target.semantic_run, semantic_object_id: target.semantic_object_id}}],
        semantic_object_id: target.semantic_object_id,
      };
      mission.map.route.push(waypoint);
      mission.map.metadata.semantic_targets.push({object_id: target.semantic_object_id, waypoint_id: waypoint.id});
      mission.selectedWaypoint = waypoint.id;
    }
    mission.dirty = true;
    syncFormFromMap();
    renderValidation();
    draw();
    await saveMap();
    notify("Inspection waypoint added", `${target.name} is now in ${mission.map.name}.`);
  }

  window.PitMission = { init, activate, refresh: refreshMaps, draw, addSemanticTarget };
}());
