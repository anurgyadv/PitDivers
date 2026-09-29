# Retroid LiDAR Minimap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an expandable bottom-left LiDAR minimap, direct LiDAR power control, configurable camera/map URLs, and automatic PC-map-to-rover-scan fallback to the existing Retroid rover-controller APK without changing its driving behaviour.

**Architecture:** Keep the existing camera WebView and dedicated 75 ms motor executor. Add a native `LidarMapView` fed by a separate `LidarRepository` executor; the repository prefers the Windows dashboard `/api/state` model and falls back to the rover `/api/lidar/revolution` model after three failures. Persist endpoint settings with `SharedPreferences`, and make the existing Windows dashboard optionally bind to the LAN.

**Tech Stack:** Kotlin, Android SDK 21+, Android Canvas/View, `HttpURLConnection`, `org.json`, JUnit 4, Python `unittest`, existing Gradle 9.6/AGP 9.4 project.

**Spec:** `docs/superpowers/specs/2026-09-29-retroid-lidar-minimap-design.md`

## Global Constraints

- Preserve motion controller `192.168.0.118`, API key `RANDOMKEY`, 75 ms ordered updates, max speed 180, deadzone 0.18, and 220 ms motor HTTP timeouts.
- Default camera URL is `http://192.168.0.119/`.
- Default Windows dashboard URL is `http://192.168.0.57:8767`.
- Default LiDAR rover URL is `http://192.168.0.99`.
- No on-screen steering controls and no MQTT migration.
- Camera, LiDAR, and map requests must never run on the motor-control executor.
- The PC provides the accumulated map; rover fallback shows only the latest local 360-degree scan.
- Keep Android `minSdk 21`, landscape orientation, and cleartext LAN HTTP support.

## Review Focus

- A huge accumulated map response must not block joystick commands or the Android UI; repository parsing stays off the UI and map models are immutable.
- Missing or malformed optional map arrays must produce a partial/offline model instead of crashing; Task 1 pins this with malformed and partial JSON tests.
- URLs containing paths, trailing slashes, or unsupported schemes must normalize predictably or be rejected; Task 1 pins these cases.
- Repeated PC failures and recovery must switch sources exactly at the third failure and switch back on the first valid PC response; Task 2 pins the transition sequence.
- Activity pause/destruction during an in-flight LiDAR request must not leak callbacks or executors; Task 5 verifies cancellation and guarded UI delivery.

---

## File Structure

- `app/src/main/java/com/pitdivers/rovercontroller/MainActivity.kt`: activity lifecycle, physical controller, UI coordination, and settings dialog.
- `app/src/main/java/com/pitdivers/rovercontroller/DriveMixer.kt`: pure, testable preservation of existing stick-to-tank mixing.
- `app/src/main/java/com/pitdivers/rovercontroller/AppConfig.kt`: defaults, URL normalization, and `SharedPreferences` persistence.
- `app/src/main/java/com/pitdivers/rovercontroller/lidar/LidarModels.kt`: immutable map/scan models and JSON parsing.
- `app/src/main/java/com/pitdivers/rovercontroller/lidar/LidarRepository.kt`: HTTP transport, polling, fallback selection, and start/stop calls.
- `app/src/main/java/com/pitdivers/rovercontroller/lidar/LidarViewport.kt`: pure fit/coordinate geometry.
- `app/src/main/java/com/pitdivers/rovercontroller/lidar/LidarMapView.kt`: Android Canvas renderer only.
- `app/src/main/res/layout/activity_main.xml`: camera, status banner, bottom-left card, controls, and expanded overlay.
- `app/src/main/res/layout/dialog_connection_settings.xml`: editable camera, dashboard, and LiDAR URLs.
- `mapping/dashboard.py`: optional LAN host binding.
- `mapping/start_demo.ps1` and `mapping/start_dashboard.ps1`: launch the dashboard on `0.0.0.0` for the Retroid.

### Task 1: Configuration, LiDAR Models, and Parsers

**Files:**
- Create: `firmware/Android/rover-controller/app/src/main/java/com/pitdivers/rovercontroller/AppConfig.kt`
- Create: `firmware/Android/rover-controller/app/src/main/java/com/pitdivers/rovercontroller/lidar/LidarModels.kt`
- Create: `firmware/Android/rover-controller/app/src/test/java/com/pitdivers/rovercontroller/AppConfigTest.kt`
- Create: `firmware/Android/rover-controller/app/src/test/java/com/pitdivers/rovercontroller/lidar/LidarModelsTest.kt`
- Modify: `firmware/Android/rover-controller/app/build.gradle`

**Interfaces:**
- Produces: `EndpointConfig(cameraUrl: String, dashboardUrl: String, lidarRoverUrl: String)`.
- Produces: `UrlNormalizer.normalizeHttpUrl(value: String): String` throwing `IllegalArgumentException` for non-HTTP(S) or missing-host values while preserving a complete camera stream path and query.
- Produces: `LidarFrame`, `MapCell`, `MapPoint`, `RoverPose`, and `LidarSource` immutable values.
- Produces: `LidarJsonParser.parseDashboard(json: String): LidarFrame` and `parseRevolution(json: String): LidarFrame`.

- [ ] **Step 1: Add JVM test JSON support and write failing configuration tests**

Add `testImplementation 'org.json:json:20240303'`. Test exact defaults, removal of a root-only trailing slash, preservation of valid stream paths and queries, acceptance of `http`/`https`, and rejection of blank, `ftp`, and hostless values.

- [ ] **Step 2: Run configuration tests and verify failure**

Run: `gradlew.bat :app:testDebugUnitTest --tests "*AppConfigTest" --console=plain`

Expected: FAIL because `EndpointConfig` and `UrlNormalizer` do not exist.

- [ ] **Step 3: Implement configuration values and persistence**

Implement `EndpointConfig.DEFAULT`, `UrlNormalizer.normalizeHttpUrl`, and `AppConfigStore(context).load()/save(config)` using one named `SharedPreferences` file.

- [ ] **Step 4: Run configuration tests and verify pass**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Write failing dashboard and revolution parser tests**

Use compact fixtures that assert occupancy cells, path, pose, points, status/reason, LiDAR running/RPM, raw 360-distance conversion, empty optional arrays, and malformed required structures. Assert non-finite numbers and wrong array element types are ignored rather than reaching the renderer.

- [ ] **Step 6: Run parser tests and verify failure**

Run: `gradlew.bat :app:testDebugUnitTest --tests "*LidarModelsTest" --console=plain`

Expected: FAIL because `LidarJsonParser` does not exist.

- [ ] **Step 7: Implement immutable models and parsers**

Parse dashboard `map.resolution`, `map.cells`, `map.path`, `map.pose`, `map.points`, `map.tracking`, `map.reason`, and `network.lidar`. Parse rover `mm` distance arrays from a revolution record into metre points using index degrees, while tolerating `distances`, `scan`, or a top-level 360-element array if firmware payload naming varies.

- [ ] **Step 8: Run Task 1 tests and commit**

Run: `gradlew.bat :app:testDebugUnitTest --tests "*AppConfigTest" --tests "*LidarModelsTest" --console=plain`

Expected: PASS.

Commit: `feat(android): add LiDAR models and endpoint settings`

### Task 2: Repository, Fallback, and LiDAR Power

**Files:**
- Create: `firmware/Android/rover-controller/app/src/main/java/com/pitdivers/rovercontroller/lidar/LidarRepository.kt`
- Create: `firmware/Android/rover-controller/app/src/test/java/com/pitdivers/rovercontroller/lidar/LidarRepositoryTest.kt`

**Interfaces:**
- Consumes: `EndpointConfig`, `LidarFrame`, and `LidarJsonParser` from Task 1.
- Produces: `HttpTransport.get(url: String, timeoutMs: Int): String` and `post(url: String, timeoutMs: Int): String`.
- Produces: `LidarRepository(configProvider: () -> EndpointConfig, transport: HttpTransport, listener: (LidarFrame) -> Unit)` with `start()`, `stop()`, `close()`, `pollOnce()`, and `setLidarEnabled(enabled: Boolean): Boolean`.
- Produces: `LidarSourceSelector.recordDashboardSuccess()` and `recordDashboardFailure(): LidarSource`, switching after exactly three failures.

- [ ] **Step 1: Write failing source-selection and fake-transport tests**

Assert two dashboard failures remain `WINDOWS_MAP`, the third selects `ROVER_SCAN`, the first valid dashboard response restores `WINDOWS_MAP`, malformed dashboard data counts as a failure, rover fallback failure retains the last valid frame with offline status, and `setLidarEnabled` posts to the exact `/api/lidar/start` or `/api/lidar/stop` URL.

- [ ] **Step 2: Run repository tests and verify failure**

Run: `gradlew.bat :app:testDebugUnitTest --tests "*LidarRepositoryTest" --console=plain`

Expected: FAIL because the repository interfaces do not exist.

- [ ] **Step 3: Implement transport, selector, and synchronous `pollOnce()`**

Use 700 ms map/revolution timeouts, immutable last-frame replacement, and no Android UI references. Ensure transport consumes response bodies and disconnects LiDAR connections because reuse is not latency-critical.

- [ ] **Step 4: Implement lifecycle scheduling**

Use a repository-owned single-thread `ScheduledExecutorService`: poll every 800 ms in Windows mode, keep probing Windows while fallback frames are served, suppress callbacks after `stop()`, and permanently shut down on `close()`.

- [ ] **Step 5: Run repository and parser tests and commit**

Run: `gradlew.bat :app:testDebugUnitTest --tests "*Lidar*Test" --console=plain`

Expected: PASS.

Commit: `feat(android): add resilient LiDAR polling`

### Task 3: Map Geometry and Native Renderer

**Files:**
- Create: `firmware/Android/rover-controller/app/src/main/java/com/pitdivers/rovercontroller/lidar/LidarViewport.kt`
- Create: `firmware/Android/rover-controller/app/src/main/java/com/pitdivers/rovercontroller/lidar/LidarMapView.kt`
- Create: `firmware/Android/rover-controller/app/src/test/java/com/pitdivers/rovercontroller/lidar/LidarViewportTest.kt`

**Interfaces:**
- Consumes: `LidarFrame`, cells, points, path, and pose from Task 1.
- Produces: `LidarViewport.fit(frame: LidarFrame, width: Float, height: Float, padding: Float): WorldTransform` and `WorldTransform.toScreen(x: Double, y: Double): ScreenPoint`.
- Produces: `LidarMapView.setFrame(frame: LidarFrame)` and normal Android `invalidate()` rendering.

- [ ] **Step 1: Write failing viewport tests**

Assert empty input uses a centred 10 m fallback extent, accumulated map cells and current scan both affect bounds, Y is inverted for Canvas coordinates, aspect ratio is preserved, padding is respected, and one extreme/non-finite point cannot generate an invalid transform.

- [ ] **Step 2: Run viewport tests and verify failure**

Run: `gradlew.bat :app:testDebugUnitTest --tests "*LidarViewportTest" --console=plain`

Expected: FAIL because viewport geometry does not exist.

- [ ] **Step 3: Implement viewport geometry**

Return finite scale/offset values for empty, single-point, compact, and room-sized models. Cap fallback scan display bounds at the parser's accepted maximum range.

- [ ] **Step 4: Run viewport tests and verify pass**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Implement `LidarMapView`**

Render a dark grid, free/explored cells, bright occupied cells, muted path, current scan points/rays, and a mint/orange rover triangle using the viewport transform. Draw only; clicks and buttons remain activity/layout responsibilities.

- [ ] **Step 6: Compile renderer and commit**

Run: `gradlew.bat :app:compileDebugKotlin --console=plain`

Expected: BUILD SUCCESSFUL.

Commit: `feat(android): render native LiDAR minimap`

### Task 4: Preserve and Test Physical Driving

**Files:**
- Create: `firmware/Android/rover-controller/app/src/main/java/com/pitdivers/rovercontroller/DriveMixer.kt`
- Create: `firmware/Android/rover-controller/app/src/test/java/com/pitdivers/rovercontroller/DriveMixerTest.kt`
- Modify: `firmware/Android/rover-controller/app/src/main/java/com/pitdivers/rovercontroller/MainActivity.kt`

**Interfaces:**
- Produces: `DriveMixer.mix(x: Float, y: Float, deadzone: Float = 0.18f, maxSpeed: Int = 180): TankCommand`.
- Consumed by: `MainActivity.sendCurrentCommand()` without changing its executor, endpoints, emergency-stop override, or lifecycle ordering.

- [ ] **Step 1: Write failing drive-contract tests**

Assert centre and values inside 0.18 produce `(0,0)`, full forward produces `(180,180)`, full reverse `(-180,-180)`, full left/right steering produces opposing values, diagonal input normalizes to maximum magnitude 180, and outputs never exceed ±180.

- [ ] **Step 2: Run drive tests and verify failure**

Run: `gradlew.bat :app:testDebugUnitTest --tests "*DriveMixerTest" --console=plain`

Expected: FAIL because `DriveMixer` does not exist.

- [ ] **Step 3: Extract existing mixing exactly and call it from `MainActivity`**

Keep `controlExecutor`, `scheduleAtFixedRate`, `/api/controller`, `/mode`, B handling, keep-alive, and 220 ms timeouts unchanged.

- [ ] **Step 4: Run drive tests and commit**

Run the Step 2 command. Expected: PASS.

Commit: `test(android): lock physical drive behaviour`

### Task 5: Android Overlay, Expansion, Settings, and Lifecycle

**Files:**
- Modify: `firmware/Android/rover-controller/app/src/main/res/layout/activity_main.xml`
- Create: `firmware/Android/rover-controller/app/src/main/res/layout/dialog_connection_settings.xml`
- Modify: `firmware/Android/rover-controller/app/src/main/java/com/pitdivers/rovercontroller/MainActivity.kt`
- Modify: `firmware/Android/rover-controller/README.md`

**Interfaces:**
- Consumes: `AppConfigStore`, `LidarRepository`, `LidarMapView`, and `DriveMixer`.
- Produces: compact bottom-left and expanded overlay states; settings save/reload; LiDAR On/Off UI.

- [ ] **Step 1: Add the compact and expanded layout states**

Place a 240×170 dp card at bottom-left with `LidarMapView`, source/status label, power button, and settings button. Add an initially hidden full-parent expanded container with the same map content and a top-right × button; use one map view moved between containers or mirror the latest immutable frame without duplicate network polling.

- [ ] **Step 2: Wire expand, collapse, and camera-preserving behaviour**

Tapping the compact canvas expands it, × collapses it, camera remains loaded underneath, and joystick/B dispatch remains at activity level in both states.

- [ ] **Step 3: Wire settings and saved URLs**

Inflate the settings dialog with current values. Validate all three fields through `UrlNormalizer`, show field errors without dismissing, persist on success, reload the camera URL, and restart repository polling with the new endpoints.

- [ ] **Step 4: Wire LiDAR state and start/stop**

Disable the power button during the request, call `setLidarEnabled`, refresh state immediately after success, and show failure in the card while retaining the last valid map.

- [ ] **Step 5: Wire lifecycle isolation**

Start LiDAR polling in `onResume`, stop it before `super.onPause`, reject late UI callbacks when the activity is stopped/destroyed, and close the repository in `onDestroy`. Do not modify motor executor ownership or scheduling.

- [ ] **Step 6: Update Android usage documentation**

Document default URLs, settings, bottom-left/expanded gestures, PC/fallback source labels, LiDAR On/Off, and the requirement that the Windows dashboard be LAN-bound for accumulated maps.

- [ ] **Step 7: Run all Android unit tests and compile**

Run: `gradlew.bat :app:testDebugUnitTest :app:compileDebugKotlin --console=plain`

Expected: BUILD SUCCESSFUL with all tests passing.

- [ ] **Step 8: Commit**

Commit: `feat(android): add expandable LiDAR overlay`

### Task 6: Expose the Windows Map Feed on the Trusted LAN

**Files:**
- Modify: `mapping/dashboard.py`
- Modify: `mapping/start_demo.ps1`
- Modify: `mapping/start_dashboard.ps1`
- Create: `mapping/test_dashboard_host.py`
- Modify: `mapping/README.md`

**Interfaces:**
- Produces: `create_parser() -> argparse.ArgumentParser` accepting `--host` with default `127.0.0.1`.
- Produces: dashboard server binding `(args.host, args.port)`.
- Android consumes only `GET /api/state`; existing same-origin POST protection remains intact.

- [ ] **Step 1: Write failing parser/default tests**

Assert no host argument yields `127.0.0.1`, `--host 0.0.0.0 --port 8767` parses both values, and the server bind helper receives the requested host.

- [ ] **Step 2: Run host tests and verify failure**

Run: `uv run --with numpy --with scipy --no-project python -m unittest mapping.test_dashboard_host -v`

Expected: FAIL because `create_parser` and bind injection do not exist.

- [ ] **Step 3: Add configurable dashboard host**

Extract parser creation, bind `ThreadingHTTPServer((args.host, args.port), ...)`, and print the actual bind address without weakening POST origin checks.

- [ ] **Step 4: Update launchers and documentation**

Pass `--host 0.0.0.0` in both PowerShell launchers, explain Windows Firewall/private-network access, and identify `/api/state` as the Android read feed. Keep the browser URL as `127.0.0.1` for local use.

- [ ] **Step 5: Run mapping regression tests and commit**

Run: `uv run --with numpy --with scipy --no-project python -m unittest mapping.test_dashboard_host mapping.test_dashboard_speed -v`

Expected: PASS.

Commit: `feat(mapping): expose map state to Retroid`

### Task 7: Full Verification and APK

**Files:**
- Modify only if verification finds a defect in files owned by Tasks 1–6.
- Output: `firmware/Android/rover-controller/app/build/outputs/apk/debug/app-debug.apk`

**Interfaces:**
- Consumes all prior tasks.
- Produces the installable debug APK and verification report.

- [ ] **Step 1: Run the focused mapping tests**

Run: `uv run --with numpy --with scipy --no-project python -m unittest mapping.test_dashboard_host mapping.test_dashboard_speed -v`

Expected: PASS.

- [ ] **Step 2: Run all Android unit tests**

Run: `gradlew.bat :app:testDebugUnitTest --console=plain`

Expected: BUILD SUCCESSFUL with zero failed tests.

- [ ] **Step 3: Build the debug APK**

Run: `gradlew.bat :app:assembleDebug --offline --console=plain`

Expected: BUILD SUCCESSFUL and `app-debug.apk` exists.

- [ ] **Step 4: Perform fixture-backed emulator checks**

Verify camera URL load, compact bottom-left map, expanded map, × collapse, saved settings after activity recreation, LiDAR toggle loading/error states, PC source, three-failure rover fallback, PC recovery, joystick continuity while map polls, and B emergency stop.

- [ ] **Step 5: Run static safety checks**

Confirm no LiDAR call references `controlExecutor`; no on-screen direction buttons exist; motor constants/endpoints remain exact; dashboard POST origin protection remains; and the APK contains no hard dependency on the PC being online.

- [ ] **Step 6: Commit verification fixes if any**

Commit only verified corrections with message: `fix(android): finalize Retroid LiDAR minimap`

