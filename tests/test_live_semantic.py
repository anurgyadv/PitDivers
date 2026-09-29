import unittest

from webapp.live_semantic import LiveObjectTracker, box_iou


class LiveSemanticTrackerTests(unittest.TestCase):
    def test_iou(self):
        self.assertAlmostEqual(box_iou([0, 0, 10, 10], [5, 0, 15, 10]), 1 / 3)
        self.assertEqual(box_iou([0, 0, 1, 1], [2, 2, 3, 3]), 0)

    def test_id_persists_for_overlapping_same_class(self):
        tracker = LiveObjectTracker()
        first = tracker.update([{"label": "door", "confidence": 0.8, "bbox_xyxy": [0, 0, 20, 20]}])
        second = tracker.update([{"label": "door", "confidence": 0.7, "bbox_xyxy": [2, 1, 22, 21]}])
        self.assertEqual(first[0]["object_id"], second[0]["object_id"])
        self.assertEqual(second[0]["track_hits"], 2)

    def test_classes_do_not_share_ids(self):
        tracker = LiveObjectTracker()
        items = tracker.update([
            {"label": "door", "confidence": 0.8, "bbox_xyxy": [0, 0, 20, 20]},
            {"label": "chair", "confidence": 0.9, "bbox_xyxy": [0, 0, 20, 20]},
        ])
        self.assertNotEqual(items[0]["track_id"], items[1]["track_id"])


if __name__ == "__main__":
    unittest.main()
