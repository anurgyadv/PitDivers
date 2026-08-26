# Claude Recommendations

Notes and suggestions from Claude for improving PitDivers. This is a living
document — nothing here is implemented yet. Pick items off it as you go.

## Improving 3D reconstruction quality

**Problem:** reconstructed models come out fuzzy and unclear.

**Root cause:** DA3's GLB export is a confidence-filtered colored *point cloud*,
not a mesh, so it inherently looks sparse and fuzzy. On top of that, the current
pipeline feeds it the weakest possible input — 800×600 MJPEG frames pulled from
the live stream, which carry JPEG compression artifacts and motion blur. Garbage
in, fuzzy cloud out. Several DA3 quality knobs are also left at their defaults
because the dashboard hardcodes the reconstruction command.

Attack it highest-leverage first.

### Tier 1 — Input image quality (dominant factor)

`webapp/core.py` runs reconstruction on keyframes pulled from the `:81/stream`
MJPEG at SVGA. That is the root problem.

- **Bump camera resolution for capture.** In
  `firmware/PitDivers_Camera_DHT11/PitDivers_Camera_DHT11.ino` the camera is
  `FRAMESIZE_SVGA` (800×600). The OV2640 supports `FRAMESIZE_UXGA` (1600×1200) —
  4× the pixels and 4× the detail DA3 has to work with. Keep live streaming at
  SVGA for latency; use full resolution only for capture.
- **Add a dedicated still-capture endpoint.** Rather than decoding blurry stream
  frames, add a `/capture` route on the ESP32 that grabs one full-resolution,
  low-compression JPEG on demand, and have the dashboard pull keyframes from that
  instead of the stream. Stream frames are optimized for framerate, not
  per-frame sharpness.
- **Lock exposure / white-balance / gain.** Auto-exposure makes brightness jump
  frame to frame, which hurts multi-view matching. Fixed settings give
  consistent frames.
- **Add rover lighting.** DA3 falls apart on dark, low-texture, or wet/reflective
  surfaces (exactly what mine walls are). An LED giving even, diffuse light is
  the single biggest real-world win. Pairs with the planned hardware additions.

### Tier 2 — Capture geometry (free, just technique)

- **Parallax, not rotation.** DA3 multi-view needs *translation* between views.
  Orbit the subject / move sideways. Spinning in place gives almost nothing to
  triangulate — a common cause of warped, unclear geometry.
- **Stop-and-shoot.** A moving rover plus rolling shutter produces smeared
  frames. This ties directly into the dashboard-teleop plan: drive → stop →
  capture → repeat. Currently keyframes save at a fixed 2 fps regardless of
  motion, so you get piles of near-identical blurry frames. 25–40 sharp,
  well-spread views beat 300 blurry ones.

### Tier 3 — DA3 / export parameters (cheap software wins in this repo)

`ReconstructionJobs._run` in `webapp/core.py` only passes `--model-dir`,
`--export-format glb`, `--export-dir`, and `--process-res`. The DA3 CLI
(`third_party/depth-anything-3/src/depth_anything_3/cli.py`) exposes several
quality levers left at default:

| Flag | Current | Suggested | Effect |
|---|---|---|---|
| `--conf-thresh-percentile` | 40 | 55–70 | Drops low-confidence floating/noise points — biggest cleanup lever |
| `--process-res` | ≤672 (UI cap) | up to 1008 offline | Sharper depth per view |
| model | DA3-Base | DA3-Large-1.1 | Much better geometry for offline runs |
| `--show-cameras` | true | false | Removes camera wireframe pyramids cluttering the scene |
| `--num-max-points` | 1M | raise with high res | Denser cloud (file-size tradeoff) |

All of these are just arguments to add to the subprocess command plus controls in
the reconstruct dialog (`webapp/static/index.html` / `app.js`) — low risk,
immediate impact. Fastest thing to ship.

### Tier 4 — Representation (the "clarity" jump)

- **Point cloud → mesh.** Add an Open3D post-step (voxel downsample → statistical
  outlier removal → estimate normals → Poisson surface reconstruction) to produce
  a solid `scene_mesh.glb`. A shaded surface reads dramatically clearer than
  points in the `model-viewer`.
- **Gaussian Splatting.** DA3 ships a GS export path
  (`utils/export/gs.py`, the `gsdpt` model). Splats render near-photorealistically
  versus point clouds, but need a GS-capable checkpoint and `infer_gs`, so it is a
  bigger lift. Worth it later.

### Suggested order of attack

1. Tier 3 — ~30 min in `core.py` + the reconstruct form; visibly cleaner results
   today.
2. Tier 1 firmware still-capture + UXGA — biggest true-quality win; pairs
   naturally with the teleop work.
3. Tier 4 Open3D meshing — most visually obvious upgrade once inputs are good.
