import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import trimesh

from vision.semantic3d.export import export_scene
from webapp.semantic import SemanticStore


class SemanticStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name) / "semantic"
        self.folder.mkdir()
        self.registry = {
            "schema_version": "1.0",
            "source_reconstruction": "source",
            "vocabulary": ["door"],
            "objects": [
                {"object_id": "door_0001", "label": "door", "confidence": .8, "centroid_world": [0, 1, 0], "bbox_min": [0, 0, 0], "bbox_max": [1, 2, .2], "point_count": 100, "observations": 2, "source_frames": [1, 2], "mask_files": ["a.png"]},
                {"object_id": "door_0002", "label": "door", "confidence": .6, "centroid_world": [2, 1, 0], "bbox_min": [1.5, 0, 0], "bbox_max": [2.5, 2, .2], "point_count": 50, "observations": 1, "source_frames": [3], "mask_files": ["b.png"]},
            ],
        }
        (self.folder / "objects.json").write_text(json.dumps(self.registry))
        self.store = SemanticStore()

    def tearDown(self):
        self.temporary.cleanup()

    def test_review_and_calibration_persist(self):
        self.store.review(self.folder, "door_0001", status="accepted", label="fire door", note="checked")
        calibration = self.store.calibrate(self.folder, "door_0001", 1, 2.0)
        saved = self.store.load(self.folder)
        self.assertEqual(saved["objects"][0]["review"]["status"], "accepted")
        self.assertEqual(saved["objects"][0]["label"], "fire door")
        self.assertAlmostEqual(calibration["meters_per_unit"], 1.0)

    def test_merge_preserves_geometry_sources(self):
        merged = self.store.merge(self.folder, ["door_0001", "door_0002"], "door")
        self.assertEqual(merged["point_count"], 150)
        self.assertEqual(merged["geometry_ids"], ["door_0001", "door_0002"])
        self.assertEqual(self.store.load(self.folder)["object_count"], 1)

    def test_spatial_split_rebuilds_scene_and_registry(self):
        source = self.folder.parent / "source"
        source.mkdir()
        base_points = np.array([[-1, 0, 0], [0, 0, 0], [1, 0, 0]], dtype=np.float32)
        trimesh.Scene(trimesh.points.PointCloud(base_points)).export(source / "scene.glb")
        clusters = np.vstack((np.column_stack((np.linspace(-.8, -.4, 30), np.zeros(30), np.zeros(30))), np.column_stack((np.linspace(.4, .8, 30), np.zeros(30), np.zeros(30))))).astype(np.float32)
        single_registry = {**self.registry, "objects": [self.registry["objects"][0]]}
        (self.folder / "objects.json").write_text(json.dumps(single_registry))
        objects = [{**self.registry["objects"][0], "points": clusters, "colours": np.zeros((60, 3), np.uint8), "point_confidence": np.ones(60)}]
        export_scene(source / "scene.glb", self.folder / "scene.glb", objects)
        children = self.store.split(self.folder, "door_0001", 0)
        self.assertEqual(len(children), 2)
        self.assertEqual(self.store.load(self.folder)["object_count"], 2)
        self.assertLess(children[0]["bbox_max"][0], children[1]["bbox_min"][0])


if __name__ == "__main__":
    unittest.main()
