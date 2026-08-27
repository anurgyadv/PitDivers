# 3D reconstruction quality — roadmap

Notes and suggestions for improving PitDivers reconstruction clarity, adapted
from Claude's review. This is a living document. **Tier 3 is implemented**
(see the reconstruct dialog); the remaining tiers are tracked follow-ups.

## Status at a glance

| Tier | Theme | Status |
|---|---|---|
| 1 | Input image quality (firmware capture) | Planned |
| 2 | Capture geometry (technique) | Planned |
| 3 | DA3 / export parameters | **Implemented** |
| 4 | Point cloud → mesh / splats | Planned |

**Problem:** reconstructed models come out fuzzy and unclear.

**Root cause:** DA3's GLB export is a confidence-filtered colored *point cloud*,
not a mesh, so it inherently looks sparse and fuzzy. On top of that, the pipeline
historically fed it the weakest possible input — 800×600 MJPEG frames pulled from
the live stream, which carry JPEG compression artifacts and motion blur. Several
DA3 quality knobs were also left at their defaults.

## Tier 3 — DA3 / export parameters (implemented)

The reconstruct dialog now exposes the DA3 quality levers that were previously
hardcoded. `ReconstructionJobs._run` in `webapp/core.py` passes them straight
through to the DA3 CLI (`third_party/depth-anything-3/src/depth_anything_3/cli.py`).

| Control (dialog) | CLI flag | Old default | New default | Effect |
|---|---|---|---|---|
| Confidence filter | `--conf-thresh-percentile` | 40 | **55** | Drops low-confidence floating/noise points — biggest clean-up lever |
| Processing resolution | `--process-res` | 504 | **672** (up to 1008) | Sharper depth per view |
| DA3 model | `--model-dir` | DA3-Base | selectable (DA3-Large-1.1 for offline) | Better geometry for offline runs |
| Camera wireframes | `--show-cameras` | shown | **hidden** | Removes camera pyramids cluttering the scene |
| Point budget | `--num-max-points` | 1M | 1M (raise to 2–4M) | Denser cloud (larger file) |

All values are per-run choices in the dialog, so nothing is locked in — the old
behaviour is still reachable by picking the lower settings.

## Tier 1 — Input image quality (planned, dominant factor)

`webapp/core.py` runs reconstruction on keyframes pulled from the `:81/stream`
MJPEG at SVGA. That is the root problem.

- **Bump camera resolution for capture.** In
  `firmware/PitDivers_Camera_DHT11/PitDivers_Camera_DHT11.ino` the camera is
  `FRAMESIZE_SVGA` (800×600). The OV2640 supports `FRAMESIZE_UXGA` (1600×1200) —
  4× the pixels. Keep live streaming at SVGA for latency; use full resolution
  only for capture.
- **Add a dedicated still-capture endpoint.** Add a `/capture` route on the
  ESP32 that grabs one full-resolution, low-compression JPEG on demand, and have
  the dashboard pull keyframes from that instead of the stream.
- **Lock exposure / white-balance / gain** for consistent multi-view matching.
- **Add rover lighting.** Even, diffuse LED light is the single biggest
  real-world win on dark, wet, low-texture mine walls.

## Tier 2 — Capture geometry (planned, free technique)

- **Parallax, not rotation.** DA3 multi-view needs *translation* between views —
  orbit the subject / move sideways rather than spinning in place.
- **Stop-and-shoot.** Drive → stop → capture → repeat. 25–40 sharp, well-spread
  views beat 300 blurry ones. Ties into the dashboard-teleop plan.

## Tier 4 — Representation (the "clarity" jump)

- **Point cloud → mesh.** ✅ Available as an offline tool:
  [`tools/mesh_from_glb.py`](../tools/mesh_from_glb.py) runs the Open3D pipeline
  (voxel downsample → statistical outlier removal → estimate/orient normals →
  Poisson surface reconstruction → density trim) on any exported `scene.glb` and
  writes a solid, shaded `*_mesh.glb`. See [`tools/README.md`](../tools/README.md).
- **Gaussian Splatting.** DA3 ships a GS export path (`utils/export/gs.py`, the
  `gsdpt` model). Splats render near-photorealistically but need a GS-capable
  checkpoint and `infer_gs` **at inference time on the source images** — it
  cannot be applied to an already-exported GLB. A bigger lift for later.

## Suggested order of attack

1. ✅ Tier 3 — DA3 parameters in the reconstruct dialog (done).
2. Tier 1 firmware still-capture + UXGA — biggest true-quality win; pairs
   naturally with the teleop work.
3. Tier 4 Open3D meshing — most visually obvious upgrade once inputs are good.
