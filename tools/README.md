# PitDivers tools

Offline helpers that operate on reconstruction outputs. These are standalone
scripts — they are not part of the dashboard runtime and have their own
dependencies.

## `mesh_from_glb.py` — point cloud → shaded surface

Turns a DA3 point-cloud `scene.glb` into a solid, shaded Poisson surface mesh
(`*_mesh.glb`) that reads far clearer than points in a 3D viewer.

Pipeline: load points + colours → voxel downsample → statistical outlier
removal → estimate + orient normals → Poisson surface reconstruction → trim
the low-density fringe → export GLB.

```bash
pip install -r tools/requirements.txt
python tools/mesh_from_glb.py path/to/scene.glb
```

Useful options:

| Flag | Default | Effect |
|---|---|---|
| `--depth` | 10 | Poisson octree depth; higher = more detail + slower (try 9–12) |
| `--voxel` | auto | Downsample spacing in model units; smaller keeps more detail |
| `--density-quantile` | 0.02 | Fraction of lowest-density Poisson vertices to trim (removes balloon artefacts) |
| `--std-ratio` | 2.0 | Statistical outlier aggressiveness (lower = more aggressive) |
| `--out` | `<input>_mesh.glb` | Output path |
| `--no-preview` | off | Skip the Open3D preview window (use on a headless box) |

**View the result** in any of these ways:

1. The Open3D preview window that opens automatically (needs a display).
2. Open the written `*_mesh.glb` in a glTF viewer — Windows 3D Viewer,
   <https://gltf-viewer.donmccurdy.com>, or the Babylon.js Sandbox.
3. Drop it into the dashboard as `runs/<name>/scene.glb` and open it in the
   built-in 3D viewer.

### A note on Gaussian Splatting

Gaussian Splatting **cannot** be applied to a finished GLB. Splats are produced
by DA3's own `infer_gs` path with a GS-capable checkpoint (`gsdpt`) run on the
original **images** — not by post-processing an exported point cloud. That is a
re-run on the GPU with the source frames, so it is out of scope for these
GLB-only tools.
