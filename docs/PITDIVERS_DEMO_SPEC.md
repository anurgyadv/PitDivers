# PitDivers: final inspection demo plan

**Demo target:** 29 September 2026. **Primary claim:** A teleoperated rover can map a small inspection area, revisit a named asset, collect repeatable evidence, and return a reviewable finding. Demonstrate a controlled bench machine fault; do not claim a mining fault diagnosis or autonomous mine deployment.

**Updated first milestone:** The team wants a hallway teach run with physical start A and target B, followed by an out-and-back run. Follow [Hallway map and out-and-back mission](HALLWAY_OUT_AND_BACK.md) for the mapping procedure, current software boundary, and navigation gates. The out-and-back physical autonomy demonstration is conditional on the lifted-wheel and short-distance tests there; the core inspection demo remains teleoperated.

## One story for both challenge options

An operator sends PitDivers to inspect **Fan A**. The rover stops at a marked standoff point, captures a photo and five seconds of motor-off audio, and associates both with its LiDAR map position and sensor readings. A local comparison scores deviation from Fan A's healthy acoustic baseline. A person receives a report with the evidence, the score, and a suggested check. This answers 2A through repeatable machine listening and 2C through remote, located, actionable inspection.

### What the judges see, in order (3–4 minutes)

1. **Context, 20 seconds:** Show the saved ROS room map and the marked Fan A inspection point. Explain the area was mapped by a manual drive.
2. **Live approach, 45 seconds:** Drive slowly by hand with the map and camera visible. Show the live LiDAR position; stop short of the fan. No automated navigation claim.
3. **Healthy evidence, 35 seconds:** With rover wheels stopped and fan running normally, capture photo, 5-second audio sample, map pose, LiDAR standoff, temperature and humidity. Display the healthy frequency spectrum and baseline score.
4. **Changed machine, 45 seconds:** Introduce a safe, reversible change on a bench fan or other test rig. Repeat from the same position, heading, operating speed and mic orientation. Show the spectrum delta and a higher anomaly score. Keep both audio clips available to replay.
5. **OpenRouter report, 45 seconds:** Show one generated inspection card with machine ID, timestamp, location, observations, evidence links, anomaly score, uncertainty and a human-review recommendation. Ask the model to describe the supplied evidence, not to invent a fault type.
6. **Evidence and recovery, 25 seconds:** Open the corresponding photo, audio, sensor payload and saved map; explain microSD scan backlog and stop-on-lost-link. Finish with the reviewer decision: inspect the mount/bearing before the next run.

If audio capture is not ready, use two prerecorded, clearly labelled clips from the same fan. The rover still performs the live map/photo inspection. If the API is unavailable, show a locally saved report generated earlier from the *same* evidence and mark it as cached.

## Today’s implementation boundary

| Already available in this repository | Must be finished and checked for tomorrow | After the demo |
| --- | --- | --- |
| Freenove LiDAR, DHT11, MPU6050 and microSD scan log; ROS RF2O + SLAM Toolbox and live room dashboard | One marked asset and repeatable inspection position; prove live motion and stop behavior | Save/reload SLAM pose graph and relocalize on a later day |
| Camera recording and offline Depth Anything 3 GLB viewer in the vision console | Photograph at inspection stop; link image to map session and asset ID | Calibrated camera–LiDAR extrinsics and metric 3D registration |
| Mission map editor, validation and simulation | Show operator-selected waypoint only; keep rover manually driven | Nav2 waypoint executor after tested localization and obstacle handling |
| Wheel command lease and stop on Wi-Fi loss in Freenove firmware | Test these behaviors on blocks with wheels clear of the ground | Additional physical stop and recovery design |
| XIAO ESP32S3 Sense PDM microphone hardware is available | Capture WAV from that board **or** use two labelled prerecorded bench clips; local FFT and baseline comparison | On-device audio inference after the scoring method is validated |

The temperature/humidity sensor measures ambient air, not machine bearing temperature. The MPU6050 on the rover measures rover motion, not machine vibration. There is no gas sensor in the current build. Report these distinctions plainly.

## Audio measurement and score

- Pick **one** machine and one speed setting. Record at least three healthy 5-second clips and one controlled changed clip, with wheels off, the same mic distance and heading, and the same surrounding noise as far as possible.
- Store raw PCM/WAV with sample rate, microphone board ID, asset ID, map session/pose, standoff distance, timestamp and run label. A XIAO ESP32S3 Sense microphone example uses 16-bit PDM mono and a stable 16 kHz sampling rate; verify the actual hardware recording before scoring.
- Compute a windowed FFT or STFT on the PC first. Compare normalized log-band energy to the **median healthy baseline for this asset**. Display spectrum overlay plus deviation score. Set a demonstration threshold from healthy-to-healthy variation; do not call the score a failure probability.
- Save both the audio and score when Wi-Fi is down. The report can be generated after reconnection.

## OpenRouter credit use

**Recommended use:** run `google/gemini-2.5-flash` or another currently available model supporting **image input and JSON Schema output** on a *selected* inspection, not continuously on every video frame. This model is listed with image input and structured output support; verify its live price and availability before the demo. The API key stays in a local environment variable named `OPENROUTER_API_KEY`, never in firmware, browser JavaScript, Git or a photo URL.

Input: one downscaled JPEG, asset name, current and baseline numeric audio features, distance, ambient temperature/humidity, timestamp, and an explicit list of evidence IDs. Include no unneeded site information. The model receives no motor-control tools and cannot mark a machine safe. Use OpenRouter's `chat/completions` endpoint with image content, `response_format.type=json_schema`, `strict=true`, and a provider that supports the requested parameters. Store the model ID, prompt version, response, request ID and usage/cost with the report. Only use the response after local schema and evidence-ID validation.

Required report fields:

```json
{
  "asset_id": "Fan A",
  "finding": "changed_from_baseline | no_clear_change | insufficient_evidence",
  "severity": "review | observe",
  "observations": ["Observed evidence only"],
  "audio_anomaly_score": 0.0,
  "evidence_ids": ["photo-id", "audio-id", "scan-id"],
  "uncertainties": ["Cause cannot be determined from this recording"],
  "recommended_human_check": "Inspect the fan mount and compare with a second recording"
}
```

Deterministic code supplies and preserves the numeric score; the model may explain it but may not revise it. Reject invented evidence IDs and unsupported measurements. If OpenRouter fails, retain the evidence and show **AI summary unavailable** while preserving the local anomaly score. A single API key budget and a per-inspection call cap prevent accidental spending. Inspect provider retention settings before sending mine-site images; request zero-data-retention routing if appropriate.

OpenRouter references: [image input](https://openrouter.ai/docs/guides/overview/multimodal/image-understanding), [JSON Schema output](https://openrouter.ai/docs/guides/features/structured-outputs), [Gemini 2.5 Flash capabilities](https://openrouter.ai/google/gemini-2.5-flash/pricing), [routing/privacy controls](https://openrouter.ai/docs/guides/get-started/sovereign-ai).

## Map, GLB and ROS roadmap

- **Tomorrow:** use LiDAR occupancy as the metric 2D map and Depth Anything GLB as visual evidence. Name the asset and inspection pose manually. If useful, show one measured span from LiDAR beside the GLB; do not imply a full 3D metric fusion.
- **Next iteration:** save SLAM Toolbox's serialized pose graph after the teaching run, reload it in localization mode for a later visit, and test localization against physical floor marks. Current saved JSON maps are visual exports, not resumable ROS pose graphs.
- **Then:** measure camera intrinsics and the rigid LiDAR-to-camera transform. Align overlapping wall/asset features, fit scale from several LiDAR distances, and show per-feature residuals. A planar LiDAR cannot validate surfaces above and below its scan height.
- **Only after repeatability:** connect Nav2 waypoint follower to the motor interface. Require valid localization, fresh obstacle data, motor timeout, physical emergency stop, and an operator override. Nav2 can run custom work at a waypoint and has a collision monitor, but these are not integrated with this rover yet.

ROS references: [SLAM Toolbox serialization/localization](https://github.com/SteveMacenski/slam_toolbox), [Nav2 waypoint follower](https://docs.nav2.org/rolling/configuration_and_development/configuration_guide/core_servers/waypoint_follower/), [Nav2 collision monitor](https://docs.nav2.org/rolling/configuration_and_development/configuration_guide/core_servers/collision_monitor/).

## Go/no-go checks before judges arrive

- Map loads and a fresh scan updates while the rover is stationary.
- Wheel stop works on button release, page close and Wi-Fi interruption, tested with wheels elevated first.
- Photo and both audio clips open from the final report; their asset ID and timestamps match.
- Healthy and changed spectra visibly differ; the score and threshold are reproducible from saved files.
- OpenRouter returns one schema-valid report with no invented measurements; cached report is ready as backup.
- If the room map or localization drifts, demonstrate the evidence capture at a fixed, marked position and describe the position as an estimate.

**Pitch sentence:** “PitDivers goes where an inspector would rather not, stops at a known asset, and returns a map-linked photo, acoustic comparison and reviewable maintenance finding instead of another hour of footage.”
