from __future__ import annotations

import unittest

import numpy as np

from webapp.autonomy import AutonomyController, normalize_ollama_url


class DummyPipeline:
    def autonomy_snapshot(self):
        return None


class AutonomyTests(unittest.TestCase):
    def test_normalizes_ollama_to_origin(self) -> None:
        self.assertEqual(
            normalize_ollama_url(" http://127.0.0.1:11434/api/chat "),
            "http://127.0.0.1:11434",
        )

    def test_matches_semantic_target_and_normalizes_bbox(self) -> None:
        controller = AutonomyController(DummyPipeline())
        controller._target = "coffee mug"
        detection = controller._semantic_detection({
            "width": 640,
            "height": 480,
            "semantic_objects": [{
                "label": "coffee mug",
                "confidence": 0.91,
                "bbox_xyxy": [160, 120, 480, 360],
            }],
        })
        self.assertIsNotNone(detection)
        self.assertAlmostEqual(detection["center_x"], 0.5)
        self.assertAlmostEqual(detection["center_y"], 0.5)
        self.assertAlmostEqual(detection["width"], 0.5)
        self.assertAlmostEqual(detection["height"], 0.5)

    def test_ignores_unmatched_semantic_object(self) -> None:
        controller = AutonomyController(DummyPipeline())
        controller._target = "bottle"
        self.assertIsNone(controller._semantic_detection({
            "width": 640,
            "height": 480,
            "semantic_objects": [{
                "label": "chair",
                "confidence": 0.99,
                "bbox_xyxy": [0, 0, 100, 100],
            }],
        }))

    def test_status_exposes_bounded_console_log(self) -> None:
        controller = AutonomyController(DummyPipeline())
        for index in range(305):
            controller._log(f"event {index}")
        logs = controller.status()["logs"]
        self.assertEqual(len(logs), 300)
        self.assertEqual(logs[0]["message"], "event 5")
        self.assertEqual(logs[-1]["id"], 305)

    def test_depth_clearance_splits_left_center_right(self) -> None:
        depth = np.ones((90, 90), dtype=np.float32)
        depth[:, :30] = 3.0
        depth[:, 30:60] = 1.0
        depth[:, 60:] = 2.0
        clearance = AutonomyController._depth_clearance({"depth": depth})
        self.assertIsNotNone(clearance)
        self.assertGreater(clearance["left"], clearance["right"])
        self.assertGreater(clearance["right"], clearance["center"])
        self.assertEqual(AutonomyController._safer_turn(clearance, 0), "left")


if __name__ == "__main__":
    unittest.main()
