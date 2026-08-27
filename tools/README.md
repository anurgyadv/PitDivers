# PitDivers tools

Offline helpers that operate on reconstruction outputs. These are standalone
scripts — they are not part of the dashboard runtime and have their own
dependencies.

## `mesh_from_glb.py` — point cloud → shaded surface

Turns a DA3 point-cloud `scene.glb` into a solid, shaded Poisson surface mesh
(`*_mesh.glb`) that reads far clearer than points in a 3D viewer.

Pipeline: load points + colours → downsample toward a point budget → statistical
outlier removal → estimate + orient normals → surface reconstruction → export GLB.

```bash
pip install -r tools/requirements.txt
python tools/mesh_from_glb.py path/to/scene.glb              # Ball-Pivoting (default)
python tools/mesh_from_glb.py path/to/scene.glb --method poisson
```

### Which method?

- **`--method bpa` (Ball-Pivoting, default)** — the triangles hug the actual
  points. Best for **open scans** — mine walls, tunnels, anything captured from
  one side. It will not balloon or bridge across gaps; it may leave small holes
  where points are sparse.
- **`--method poisson`** — fits a smooth *watertight* surface. Great for
  closed-ish objects, but on an open scene it stretches skin across gaps and
  past the edges ("ballooning"). The tool auto-crops the result to the point
  cloud and trims low-density vertices to reduce this, but BPA is safer for
  wall/tunnel scans.

If your Poisson result looked inflated and blobby, that's expected on an open
scan — switch to `--method bpa`.

### Options

| Flag | Default | Effect |
|---|---|---|
| `--method` | `bpa` | `bpa` (open scans) or `poisson` (closed objects) |
| `--target-points` | 600000 | Auto-downsample aims for ~this many points. Higher = more detail, but normal orientation slows past ~1M |
| `--voxel` | auto | Explicit downsample spacing (overrides `--target-points`); smaller keeps more detail |
| `--radius-mult` | 2.0 | [bpa] Ball radius as a multiple of average point spacing (try 1.5–3; larger fills more holes) |
| `--depth` | 10 | [poisson] Octree depth; higher = more detail + slower (try 9–12) |
| `--density-quantile` | 0.04 | [poisson] Fraction of lowest-density vertices to trim (removes balloons) |
| `--std-ratio` | 2.0 | Statistical outlier aggressiveness (lower = more aggressive) |
| `--out` | `<input>_mesh.glb` | Output path |
| `--no-preview` | off | Skip the Open3D preview window (use on a headless box) |

> **Note on speed:** the normal-orientation step grows with point count. On a
> multi-million-point cloud, keep `--target-points` around 400k–800k (the
> default 600k is a good start); raise it only if you need finer detail and can
> wait. Your earlier run auto-decimated a 5M cloud down to 180k — the new
> default keeps far more.

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
