from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np


@dataclass
class Observation:
    label: str
    frame_id: int
    detection_confidence: float
    points: np.ndarray
    colours: np.ndarray
    point_confidence: np.ndarray
    mask_file: str

    @property
    def centroid(self) -> np.ndarray:
        return np.median(self.points, axis=0)

    @property
    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return np.percentile(self.points, 2, axis=0), np.percentile(self.points, 98, axis=0)


def _bbox_gap(a: Observation, b: Observation) -> float:
    a_min, a_max = a.bounds
    b_min, b_max = b.bounds
    gap = np.maximum(0.0, np.maximum(a_min - b_max, b_min - a_max))
    return float(np.linalg.norm(gap))


def _appearance_distance(a: Observation, b: Observation) -> float:
    left = np.median(a.colours.astype(np.float32), axis=0)
    right = np.median(b.colours.astype(np.float32), axis=0)
    return float(np.linalg.norm(left - right) / (255.0 * np.sqrt(3.0)))


def _voxel_downsample(points: np.ndarray, colours: np.ndarray, confidence: np.ndarray, voxel: float, limit: int = 25000):
    if not len(points):
        return points, colours, confidence
    keys = np.floor(points / max(voxel, 1e-6)).astype(np.int64)
    _, indices = np.unique(keys, axis=0, return_index=True)
    if len(indices) > limit:
        indices = indices[np.linspace(0, len(indices) - 1, limit, dtype=np.int64)]
    return points[indices], colours[indices], confidence[indices]


def fuse_observations(observations: list[Observation]) -> list[dict]:
    """Associate same-class observations using 3D bounds and centroid proximity."""
    if not observations:
        return []
    centroids = np.stack([item.centroid for item in observations])
    scene_span = max(float(np.linalg.norm(np.ptp(centroids, axis=0))), 1e-3)
    object_spans = [float(np.linalg.norm(item.bounds[1] - item.bounds[0])) for item in observations]
    merge_radius = max(scene_span * 0.025, float(np.median(object_spans)) * 0.40, 1e-3)
    parent = list(range(len(observations)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    by_label: dict[str, list[int]] = defaultdict(list)
    for index, observation in enumerate(observations):
        by_label[observation.label].append(index)
    for indices in by_label.values():
        for offset, left in enumerate(indices):
            for right in indices[offset + 1:]:
                if abs(observations[left].frame_id - observations[right].frame_id) > 30:
                    continue
                centroid_distance = float(np.linalg.norm(observations[left].centroid - observations[right].centroid))
                appearance_distance = _appearance_distance(observations[left], observations[right])
                if appearance_distance <= 0.32 and _bbox_gap(observations[left], observations[right]) <= merge_radius and centroid_distance <= merge_radius * 2.0:
                    union(left, right)

    groups: dict[int, list[Observation]] = defaultdict(list)
    for index, observation in enumerate(observations):
        groups[find(index)].append(observation)

    counters: dict[str, int] = defaultdict(int)
    objects = []
    for group in sorted(groups.values(), key=lambda items: (items[0].label, min(item.frame_id for item in items))):
        label = group[0].label
        counters[label] += 1
        object_id = f"{label.lower().replace(' ', '_')}_{counters[label]:04d}"
        points = np.concatenate([item.points for item in group])
        colours = np.concatenate([item.colours for item in group])
        confidence = np.concatenate([item.point_confidence for item in group])
        points, colours, confidence = _voxel_downsample(points, colours, confidence, scene_span * 0.0025)
        source_frames = sorted({item.frame_id for item in group})
        weights = np.array([item.detection_confidence for item in group], dtype=np.float64)
        objects.append({
            "object_id": object_id,
            "label": label,
            "confidence": float(np.average(weights, weights=np.maximum(weights, 1e-6))),
            "centroid_world": np.median(points, axis=0).tolist(),
            "bbox_min": np.min(points, axis=0).tolist(),
            "bbox_max": np.max(points, axis=0).tolist(),
            "point_count": int(len(points)),
            "observations": len(group),
            "source_frames": source_frames,
            "mask_files": [item.mask_file for item in group],
            "points": points,
            "colours": colours,
            "point_confidence": confidence,
        })
    return objects
