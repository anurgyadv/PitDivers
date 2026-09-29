from __future__ import annotations

import cv2
import numpy as np


def project_mask(
    mask: np.ndarray,
    depth: np.ndarray,
    depth_confidence: np.ndarray,
    intrinsics: np.ndarray,
    extrinsics_w2c: np.ndarray,
    detection_confidence: float,
    *,
    erosion_pixels: int = 1,
    confidence_percentile: float = 35.0,
    max_points: int = 3000,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Back-project accepted mask pixels into the DA3 world coordinate frame."""
    height, width = depth.shape
    if mask.shape != (height, width):
        mask = cv2.resize(mask.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST)
    mask = mask.astype(bool)
    if erosion_pixels > 0:
        size = erosion_pixels * 2 + 1
        mask = cv2.erode(mask.astype(np.uint8), np.ones((size, size), np.uint8), iterations=1).astype(bool)

    valid_depth = np.isfinite(depth) & (depth > 0)
    finite_conf = depth_confidence[np.isfinite(depth_confidence)]
    if finite_conf.size:
        cutoff = float(np.percentile(finite_conf, confidence_percentile))
        low, high = np.percentile(finite_conf, [5, 95])
        geometry_score = np.clip((depth_confidence - low) / max(float(high - low), 1e-6), 0.0, 1.0)
        valid = mask & valid_depth & np.isfinite(depth_confidence) & (depth_confidence >= cutoff)
    else:
        geometry_score = np.ones_like(depth, dtype=np.float32)
        valid = mask & valid_depth

    rows, cols = np.nonzero(valid)
    if not len(rows):
        return (np.empty((0, 3), np.float32), np.empty((0,), np.float32), np.empty((0, 2), np.int32))
    if len(rows) > max_points:
        selected = np.linspace(0, len(rows) - 1, max_points, dtype=np.int64)
        rows, cols = rows[selected], cols[selected]

    z = depth[rows, cols].astype(np.float64)
    fx, fy = float(intrinsics[0, 0]), float(intrinsics[1, 1])
    cx, cy = float(intrinsics[0, 2]), float(intrinsics[1, 2])
    camera_points = np.column_stack(((cols - cx) * z / fx, (rows - cy) * z / fy, z, np.ones_like(z)))

    w2c = np.eye(4, dtype=np.float64)
    w2c[:3, :4] = extrinsics_w2c
    world_points = (np.linalg.inv(w2c) @ camera_points.T).T[:, :3]
    confidence = (float(detection_confidence) * geometry_score[rows, cols]).astype(np.float32)
    pixels = np.column_stack((cols, rows)).astype(np.int32)
    return world_points.astype(np.float32), confidence, pixels


def apply_transform(points: np.ndarray, transform: np.ndarray) -> np.ndarray:
    homogeneous = np.column_stack((points, np.ones(len(points), dtype=points.dtype)))
    return (transform @ homogeneous.T).T[:, :3].astype(np.float32)
