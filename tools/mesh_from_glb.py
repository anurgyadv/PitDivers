#!/usr/bin/env python3
"""Turn a DA3 point-cloud GLB into a shaded Poisson surface mesh (GLB).

DA3 exports ``scene.glb`` as a *colored point cloud*, which reads fuzzy in the
model viewer. This tool runs the Open3D clean-up + surface reconstruction
pipeline and writes a solid, shaded ``*_mesh.glb`` that renders far clearer:

    load points + colours  ->  voxel downsample  ->  statistical outlier removal
    ->  estimate + orient normals  ->  Poisson surface reconstruction
    ->  trim low-density fringe  ->  export GLB

Usage
-----
    pip install open3d trimesh numpy
    python tools/mesh_from_glb.py path/to/scene.glb

    # tune it
    python tools/mesh_from_glb.py scene.glb --depth 11 --voxel 0.004 \
        --density-quantile 0.03 --out scene_mesh.glb

Then view the result:
  * an Open3D preview window opens automatically (unless --no-preview) on a
    machine with a display;
  * open the written ``*_mesh.glb`` in any glTF viewer (Windows 3D Viewer,
    https://gltf-viewer.donmccurdy.com, Babylon Sandbox); or
  * drop it into the PitDivers dashboard as ``runs/<name>/scene.glb`` and open
    it in the built-in 3D viewer.

Note: this only meshes an existing point cloud. Gaussian Splatting is NOT a
post-process of a GLB — it needs DA3's ``infer_gs`` with a GS checkpoint run on
the original images.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


def load_point_cloud(path: Path):
    """Load the densest point/vertex geometry (the cloud, not camera wireframes)."""
    import trimesh

    loaded = trimesh.load(str(path), process=False, force="scene")
    geometries = list(loaded.geometry.values()) if hasattr(loaded, "geometry") else [loaded]

    best_xyz: np.ndarray | None = None
    best_rgb: np.ndarray | None = None
    for geometry in geometries:
        vertices = np.asarray(getattr(geometry, "vertices", np.empty((0, 3))), dtype=np.float64)
        if vertices.shape[0] < 4:
            continue  # skip tiny geometry such as camera wireframes
        if best_xyz is not None and vertices.shape[0] <= best_xyz.shape[0]:
            continue

        colors = None
        raw = getattr(geometry, "colors", None)  # trimesh.PointCloud
        if raw is None:
            visual = getattr(geometry, "visual", None)
            raw = getattr(visual, "vertex_colors", None)  # trimesh.Trimesh
        raw = np.asarray(raw) if raw is not None else None
        if raw is not None and raw.shape[0] == vertices.shape[0]:
            colors = raw[:, :3].astype(np.float64) / 255.0
        else:
            colors = np.full((vertices.shape[0], 3), 0.6)

        best_xyz, best_rgb = vertices, colors

    if best_xyz is None:
        sys.exit(f"No point/vertex geometry found in {path}")
    return best_xyz, best_rgb


def export_glb(mesh, out: Path) -> None:
    """Write an Open3D triangle mesh to GLB via trimesh (keeps vertex colours)."""
    import trimesh

    vertices = np.asarray(mesh.vertices)
    faces = np.asarray(mesh.triangles)
    vertex_colors = np.asarray(mesh.vertex_colors)
    kwargs: dict = {}
    if vertex_colors.shape[0] == vertices.shape[0] and vertex_colors.size:
        kwargs["vertex_colors"] = (np.clip(vertex_colors, 0, 1) * 255).astype(np.uint8)
    normals = np.asarray(mesh.vertex_normals)
    if normals.shape[0] == vertices.shape[0] and normals.size:
        kwargs["vertex_normals"] = normals
    trimesh.Trimesh(vertices=vertices, faces=faces, **kwargs).export(str(out))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("glb", type=Path, help="Input DA3 point-cloud GLB (e.g. scene.glb)")
    parser.add_argument("--out", type=Path, default=None, help="Output GLB path (default: <input>_mesh.glb)")
    parser.add_argument("--voxel", type=float, default=0.0,
                        help="Downsample voxel size in model units (0 = auto from scene size)")
    parser.add_argument("--depth", type=int, default=10,
                        help="Poisson octree depth: higher = more detail + slower (try 9-12)")
    parser.add_argument("--density-quantile", type=float, default=0.02,
                        help="Trim this lowest fraction of Poisson vertices to remove balloon artefacts")
    parser.add_argument("--neighbors", type=int, default=20, help="Statistical outlier: neighbours")
    parser.add_argument("--std-ratio", type=float, default=2.0, help="Statistical outlier: std ratio")
    parser.add_argument("--no-preview", action="store_true", help="Do not open an Open3D preview window")
    args = parser.parse_args()

    if not args.glb.is_file():
        sys.exit(f"File not found: {args.glb}")

    import open3d as o3d

    xyz, rgb = load_point_cloud(args.glb)
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(xyz)
    pcd.colors = o3d.utility.Vector3dVector(np.clip(rgb, 0, 1))
    print(f"Loaded {len(xyz):,} points from {args.glb.name}")

    voxel = args.voxel
    if voxel <= 0:
        diag = float(np.linalg.norm(np.asarray(pcd.get_max_bound()) - np.asarray(pcd.get_min_bound())))
        voxel = max(diag * 0.0025, 1e-6)
    pcd = pcd.voxel_down_sample(voxel)
    print(f"Voxel downsample (size={voxel:.5f}) -> {len(pcd.points):,} points")

    pcd, _ = pcd.remove_statistical_outlier(nb_neighbors=args.neighbors, std_ratio=args.std_ratio)
    print(f"Outlier removal -> {len(pcd.points):,} points")
    if len(pcd.points) < 100:
        sys.exit("Too few points survived cleaning; try a smaller --voxel or looser --std-ratio")

    pcd.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel * 3.0, max_nn=30))
    pcd.orient_normals_consistent_tangent_plane(30)
    print("Estimated and oriented normals")

    mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd, depth=args.depth)
    densities = np.asarray(densities)
    if 0.0 < args.density_quantile < 1.0 and densities.size:
        keep = densities > np.quantile(densities, args.density_quantile)
        mesh.remove_vertices_by_mask(~keep)
    mesh.compute_vertex_normals()
    print(f"Poisson mesh (depth={args.depth}) -> {len(mesh.vertices):,} vertices, "
          f"{len(mesh.triangles):,} triangles")

    out = args.out or args.glb.with_name(f"{args.glb.stem}_mesh.glb")
    export_glb(mesh, out)
    print(f"Wrote {out}")

    if not args.no_preview:
        try:
            o3d.visualization.draw_geometries([mesh], window_name=f"{args.glb.stem} mesh", width=1280, height=800)
        except Exception as exc:  # headless box, no display, etc.
            print(f"(Preview window unavailable: {exc}. Open {out} in a glTF viewer instead.)")


if __name__ == "__main__":
    main()
