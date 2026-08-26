"""Grow an approximate DA3 point cloud from a live ESP32 MJPEG stream.

This is a lightweight incremental mapper for demonstrations. It runs DA3 on
overlapping keyframe windows, aligns each new window through shared camera
poses, and appends newly observed points to an Open3D viewer.
"""

from __future__ import annotations

import argparse
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import open3d as o3d
import torch

from depth_anything_3.api import DepthAnything3
from live_da3_depth import LatestFrameCapture


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live expanding DA3 point-cloud map")
    parser.add_argument("--stream-url", required=True)
    parser.add_argument("--model", default="depth-anything/DA3-BASE")
    parser.add_argument("--process-res", type=int, default=392)
    parser.add_argument("--keyframe-fps", type=float, default=2.0)
    parser.add_argument("--window-size", type=int, default=8)
    parser.add_argument("--step-size", type=int, default=3)
    parser.add_argument(
        "--point-stride",
        type=int,
        default=4,
        help="Keep one point every N pixels in each dimension.",
    )
    parser.add_argument("--confidence-percentile", type=float, default=45.0)
    parser.add_argument("--max-points", type=int, default=1_000_000)
    parser.add_argument("--keyframe-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def camera_poses(extrinsics: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return camera centers and camera-to-world rotations from W2C matrices."""
    rotations_w2c = extrinsics[:, :3, :3]
    translations = extrinsics[:, :3, 3]
    rotations_c2w = np.transpose(rotations_w2c, (0, 2, 1))
    centers = -np.einsum("nij,nj->ni", rotations_c2w, translations)
    return centers, rotations_c2w


def nearest_rotation(matrix: np.ndarray) -> np.ndarray:
    u, _, vt = np.linalg.svd(matrix)
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vt
    return rotation


def estimate_similarity(
    local_centers: np.ndarray,
    local_rotations: np.ndarray,
    global_centers: np.ndarray,
    global_rotations: np.ndarray,
) -> tuple[float, np.ndarray, np.ndarray]:
    """Estimate q_global = scale * rotation @ q_local + translation."""
    rotations = [
        global_rotations[index] @ local_rotations[index].T
        for index in range(len(local_centers))
    ]
    rotation = nearest_rotation(np.mean(rotations, axis=0))

    ratios: list[float] = []
    for first in range(len(local_centers)):
        for second in range(first + 1, len(local_centers)):
            local_distance = np.linalg.norm(local_centers[first] - local_centers[second])
            global_distance = np.linalg.norm(global_centers[first] - global_centers[second])
            if local_distance > 1e-5 and global_distance > 1e-5:
                ratios.append(float(global_distance / local_distance))

    scale = float(np.median(ratios)) if ratios else 1.0
    scale = float(np.clip(scale, 0.25, 4.0))
    rotated_centers = scale * (local_centers @ rotation.T)
    translation = np.mean(global_centers - rotated_centers, axis=0)
    return scale, rotation, translation


def points_from_view(
    depth: np.ndarray,
    confidence: np.ndarray,
    image_rgb: np.ndarray,
    intrinsic: np.ndarray,
    extrinsic: np.ndarray,
    stride: int,
    confidence_percentile: float,
) -> tuple[np.ndarray, np.ndarray]:
    height, width = depth.shape
    rows = np.arange(0, height, stride)
    columns = np.arange(0, width, stride)
    grid_x, grid_y = np.meshgrid(columns, rows)

    sampled_depth = depth[::stride, ::stride]
    sampled_confidence = confidence[::stride, ::stride]
    sampled_colors = image_rgb[::stride, ::stride]

    finite = np.isfinite(sampled_depth) & (sampled_depth > 0)
    if np.any(finite):
        confidence_cutoff = np.percentile(
            sampled_confidence[finite], confidence_percentile
        )
        far_cutoff = np.percentile(sampled_depth[finite], 99.0)
        valid = (
            finite
            & (sampled_confidence >= confidence_cutoff)
            & (sampled_depth <= far_cutoff)
        )
    else:
        valid = finite

    if not np.any(valid):
        return np.empty((0, 3)), np.empty((0, 3))

    pixels = np.stack(
        [grid_x[valid], grid_y[valid], np.ones(np.count_nonzero(valid))], axis=1
    )
    rays = pixels @ np.linalg.inv(intrinsic).T
    camera_points = rays * sampled_depth[valid, None]

    rotation_w2c = extrinsic[:3, :3]
    translation_w2c = extrinsic[:3, 3]
    local_points = (camera_points - translation_w2c) @ rotation_w2c
    colors = sampled_colors[valid].astype(np.float64) / 255.0
    return local_points, colors


def main() -> None:
    args = parse_args()
    if args.window_size < 4:
        raise SystemExit("--window-size must be at least 4")
    if not 1 <= args.step_size < args.window_size:
        raise SystemExit("--step-size must be between 1 and window-size - 1")
    if args.keyframe_fps <= 0 or args.point_stride <= 0:
        raise SystemExit("Frame rate and point stride must be greater than zero")
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable")

    args.keyframe_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading {args.model} on {torch.cuda.get_device_name(0)} ...")
    model = DepthAnything3.from_pretrained(args.model).to("cuda").eval()
    capture = LatestFrameCapture(args.stream_url).start()

    visualizer = o3d.visualization.Visualizer()
    visualizer.create_window("PitDivers - Live Expanding DA3 Map", 1280, 720)
    render_options = visualizer.get_render_option()
    render_options.background_color = np.asarray([0.03, 0.03, 0.04])
    render_options.point_size = 2.0

    cloud = o3d.geometry.PointCloud()
    geometry_added = False
    all_points = np.empty((0, 3), dtype=np.float64)
    all_colors = np.empty((0, 3), dtype=np.float64)
    rng = np.random.default_rng(42)

    window: deque[tuple[int, np.ndarray]] = deque(maxlen=args.window_size)
    global_centers: dict[int, np.ndarray] = {}
    global_rotations: dict[int, np.ndarray] = {}
    next_frame_id = 0
    new_since_update = 0
    last_sequence = -1
    last_keyframe_at = 0.0

    print(
        "Move slowly with side-to-side parallax. Close the 3D window or press Ctrl+C to stop."
    )

    try:
        running = True
        while running:
            running = visualizer.poll_events()
            visualizer.update_renderer()

            frame_bgr, sequence = capture.latest()
            now = time.perf_counter()
            if (
                frame_bgr is None
                or sequence == last_sequence
                or now - last_keyframe_at < 1.0 / args.keyframe_fps
            ):
                time.sleep(0.005)
                continue

            frame_path = args.keyframe_dir / f"frame_{next_frame_id:06d}.jpg"
            cv2.imwrite(str(frame_path), frame_bgr)
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            window.append((next_frame_id, frame_rgb))
            next_frame_id += 1
            new_since_update += 1
            last_sequence = sequence
            last_keyframe_at = now

            if len(window) < args.window_size or new_since_update < args.step_size:
                print(
                    f"Captured {next_frame_id} keyframes; waiting for window "
                    f"{len(window)}/{args.window_size}",
                    end="\r",
                )
                continue

            frame_ids = [item[0] for item in window]
            frames_rgb = [item[1] for item in window]
            started_at = time.perf_counter()
            prediction = model.inference(
                frames_rgb,
                process_res=args.process_res,
                process_res_method="upper_bound_resize",
            )
            local_centers, local_rotations = camera_poses(prediction.extrinsics)

            overlap_indices = [
                index
                for index, frame_id in enumerate(frame_ids)
                if frame_id in global_centers
            ]
            if overlap_indices:
                scale, map_rotation, map_translation = estimate_similarity(
                    local_centers[overlap_indices],
                    local_rotations[overlap_indices],
                    np.asarray([global_centers[frame_ids[i]] for i in overlap_indices]),
                    np.asarray([global_rotations[frame_ids[i]] for i in overlap_indices]),
                )
            else:
                scale = 1.0
                map_rotation = np.eye(3)
                map_translation = np.zeros(3)

            transformed_centers = scale * (local_centers @ map_rotation.T) + map_translation
            transformed_rotations = np.einsum(
                "ij,njk->nik", map_rotation, local_rotations
            )
            for index, frame_id in enumerate(frame_ids):
                global_centers[frame_id] = transformed_centers[index]
                global_rotations[frame_id] = transformed_rotations[index]

            new_indices = [
                index
                for index, frame_id in enumerate(frame_ids)
                if frame_id >= next_frame_id - new_since_update
            ]
            if not geometry_added:
                new_indices = list(range(len(frame_ids)))

            point_batches: list[np.ndarray] = []
            color_batches: list[np.ndarray] = []
            for index in new_indices:
                local_points, colors = points_from_view(
                    prediction.depth[index],
                    prediction.conf[index],
                    prediction.processed_images[index],
                    prediction.intrinsics[index],
                    prediction.extrinsics[index],
                    args.point_stride,
                    args.confidence_percentile,
                )
                global_points = scale * (local_points @ map_rotation.T) + map_translation
                point_batches.append(global_points)
                color_batches.append(colors)

            if point_batches:
                all_points = np.concatenate([all_points, *point_batches], axis=0)
                all_colors = np.concatenate([all_colors, *color_batches], axis=0)

            if len(all_points) > args.max_points:
                keep = rng.choice(len(all_points), args.max_points, replace=False)
                all_points = all_points[keep]
                all_colors = all_colors[keep]

            cloud.points = o3d.utility.Vector3dVector(all_points)
            cloud.colors = o3d.utility.Vector3dVector(all_colors)
            if not geometry_added:
                visualizer.add_geometry(cloud)
                visualizer.reset_view_point(True)
                geometry_added = True
            else:
                visualizer.update_geometry(cloud)

            elapsed = time.perf_counter() - started_at
            print(
                f"\nMap update: {next_frame_id} frames, {len(all_points):,} points, "
                f"{elapsed:.2f}s"
            )
            new_since_update = 0
    except KeyboardInterrupt:
        pass
    finally:
        capture.close()
        if geometry_added:
            o3d.io.write_point_cloud(str(args.output), cloud, write_ascii=False)
            print(f"Saved expanding map to {args.output.resolve()}")
        visualizer.destroy_window()


if __name__ == "__main__":
    main()
