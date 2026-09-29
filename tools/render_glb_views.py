#!/usr/bin/env python3
"""Render a coloured GLB point cloud as a four-view PNG contact sheet."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import trimesh


def load_largest_geometry(path: Path) -> tuple[np.ndarray, np.ndarray]:
    loaded = trimesh.load(path, process=False, force="scene")
    geometry = max(loaded.geometry.values(), key=lambda item: len(item.vertices))
    points = np.asarray(geometry.vertices, dtype=np.float32)
    raw = getattr(geometry, "colors", None)
    if raw is None:
        raw = getattr(getattr(geometry, "visual", None), "vertex_colors", None)
    colors = np.asarray(raw)[:, :3] / 255.0 if raw is not None else np.full_like(points, 0.75)
    return points, colors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("glb", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--points", type=int, default=140_000)
    args = parser.parse_args()

    points, colors = load_largest_geometry(args.glb)
    # Remove extreme reconstruction outliers before choosing the view volume.
    low, high = np.quantile(points, [0.005, 0.995], axis=0)
    keep = np.all((points >= low) & (points <= high), axis=1)
    points, colors = points[keep], colors[keep]

    rng = np.random.default_rng(7)
    if len(points) > args.points:
        chosen = rng.choice(len(points), args.points, replace=False)
        points, colors = points[chosen], colors[chosen]

    center = np.median(points, axis=0)
    points = points - center
    _, _, basis = np.linalg.svd(points, full_matrices=False)
    points = points @ basis.T
    spans = np.ptp(points, axis=0)

    fig = plt.figure(figsize=(14, 10), facecolor="#101216")
    views = [(22, -60, "Perspective"), (90, -90, "Top"), (8, -90, "Front"), (8, 0, "Side")]
    for index, (elev, azim, title) in enumerate(views, start=1):
        axis = fig.add_subplot(2, 2, index, projection="3d", facecolor="#101216")
        axis.scatter(points[:, 0], points[:, 1], points[:, 2], c=colors, s=0.18, linewidths=0)
        axis.view_init(elev=elev, azim=azim)
        axis.set_box_aspect(np.maximum(spans, spans.max() * 0.08))
        axis.set_title(title, color="white", pad=8)
        axis.set_axis_off()

    fig.suptitle("Rover run 1 — COLMAP-guided DA3 reconstruction", color="white", fontsize=16)
    fig.tight_layout(rect=(0, 0, 1, 0.96), pad=0.4)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=180, facecolor=fig.get_facecolor(), bbox_inches="tight")


if __name__ == "__main__":
    main()
