import unittest
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vision/.venv/Lib/site-packages"))

from vision.semantic3d.fusion import Observation, fuse_observations
from vision.semantic3d.projection import project_mask
from vision.semantic3d.surface import anchor_objects_to_points


class Semantic3DTests(unittest.TestCase):
    def test_projection_identity_camera(self):
        mask = np.zeros((3, 3), dtype=np.uint8)
        mask[1, 1] = 1
        depth = np.full((3, 3), 2.0, dtype=np.float32)
        confidence = np.ones((3, 3), dtype=np.float32)
        intrinsics = np.array([[2, 0, 1], [0, 2, 1], [0, 0, 1]], dtype=np.float32)
        points, scores, pixels = project_mask(mask, depth, confidence, intrinsics, np.eye(4, dtype=np.float32)[:3], 0.8, erosion_pixels=0)
        np.testing.assert_allclose(points, [[0, 0, 2]])
        self.assertEqual(pixels.tolist(), [[1, 1]])
        self.assertEqual(scores[0], np.float32(0.0))


    def test_fusion_merges_overlapping_same_class(self):
        points = np.array([[0, 0, 1], [0.01, 0, 1], [0, 0.01, 1]], dtype=np.float32)
        common = dict(label="door", detection_confidence=0.8, colours=np.zeros((3, 3), np.uint8), point_confidence=np.ones(3), mask_file="mask.png")
        observations = [Observation(frame_id=0, points=points, **common), Observation(frame_id=1, points=points + 0.005, **common)]
        objects = fuse_observations(observations)
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]["observations"], 2)

    def test_fusion_keeps_distant_same_class_instances_separate(self):
        points = np.array([[0, 0, 1], [0.01, 0, 1], [0, 0.01, 1]], dtype=np.float32)
        common = dict(label="door", detection_confidence=0.8, colours=np.zeros((3, 3), np.uint8), point_confidence=np.ones(3), mask_file="mask.png")
        observations = [Observation(frame_id=0, points=points, **common), Observation(frame_id=1, points=points + np.array([1, 0, 0]), **common)]
        self.assertEqual(len(fuse_observations(observations)), 2)

    def test_surface_anchor_snaps_and_rejects_floating_objects(self):
        surface = np.array([[0, 0, 0], [0.01, 0, 0], [1, 1, 1]], dtype=np.float32)
        common = {
            "colours": np.zeros((2, 3), np.uint8),
            "point_confidence": np.ones(2),
        }
        objects = [
            {"object_id": "door_0001", "points": surface[:2] + 0.001, **common},
            {"object_id": "door_0002", "points": np.array([[3, 3, 3], [3.1, 3, 3]]), **common},
        ]
        anchored = anchor_objects_to_points(objects, surface, distance_ratio=0.02, minimum_points=1)
        self.assertEqual([item["object_id"] for item in anchored], ["door_0001"])
        np.testing.assert_allclose(anchored[0]["points"], surface[:2])


if __name__ == "__main__":
    unittest.main()
