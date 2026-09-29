from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial import cKDTree


def anchor_objects_to_points(
    objects: list[dict],
    surface_points: np.ndarray,
    *,
    distance_ratio: float = 0.01,
    minimum_support: float = 0.15,
    minimum_points: int = 20,
) -> list[dict]:
    """Snap semantic points onto a reconstruction and reject floating objects."""
    surface_points = np.asarray(surface_points, dtype=np.float32)
    if not len(surface_points):
        return []
    scene_diagonal = float(np.linalg.norm(np.ptp(surface_points, axis=0)))
    maximum_distance = max(scene_diagonal * distance_ratio, 1e-5)
    tree = cKDTree(surface_points)
    anchored = []
    for item in objects:
        points = np.asarray(item["points"], dtype=np.float32)
        if not len(points):
            continue
        distances, indices = tree.query(points, k=1, workers=-1)
        supported = distances <= maximum_distance
        support_ratio = float(np.mean(supported))
        if int(supported.sum()) < minimum_points or support_ratio < minimum_support:
            continue
        clean = dict(item)
        clean["points"] = surface_points[indices[supported]].copy()
        clean["colours"] = np.asarray(item["colours"])[supported]
        clean["point_confidence"] = np.asarray(item["point_confidence"])[supported]
        clean["surface_support"] = support_ratio
        clean["surface_max_distance"] = maximum_distance
        clean["centroid_world"] = np.median(clean["points"], axis=0).tolist()
        clean["bbox_min"] = np.min(clean["points"], axis=0).tolist()
        clean["bbox_max"] = np.max(clean["points"], axis=0).tolist()
        clean["point_count"] = int(len(clean["points"]))
        anchored.append(clean)
    return anchored


def anchor_objects_to_scene(base_scene: Path, objects: list[dict]) -> list[dict]:
    scene = trimesh.load(str(base_scene), process=False, force="scene")
    point_sets = []
    for node_name in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node_name]
        vertices = np.asarray(scene.geometry[geometry_name].vertices)
        point_sets.append(trimesh.transform_points(vertices, transform))
    surface_points = np.concatenate(point_sets) if point_sets else np.empty((0, 3), dtype=np.float32)
    return anchor_objects_to_points(objects, surface_points)
