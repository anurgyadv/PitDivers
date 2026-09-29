from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def box_iou(a: list[float], b: list[float]) -> float:
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[2], b[2])
    bottom = min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


@dataclass
class _Track:
    track_id: int
    label: str
    bbox: list[float]
    last_frame: int
    hits: int = 1


class LiveObjectTracker:
    """Small deterministic tracker for low-rate semantic detections."""

    def __init__(self, minimum_iou: float = 0.2, maximum_missed: int = 4) -> None:
        self.minimum_iou = minimum_iou
        self.maximum_missed = maximum_missed
        self._next_id = 1
        self._frame = 0
        self._tracks: dict[int, _Track] = {}

    def reset(self) -> None:
        self._next_id = 1
        self._frame = 0
        self._tracks.clear()

    def update(self, detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self._frame += 1
        unused = set(self._tracks)
        output: list[dict[str, Any]] = []
        for detection in sorted(detections, key=lambda item: float(item.get("confidence", 0)), reverse=True):
            label = str(detection["label"])
            bbox = [float(value) for value in detection["bbox_xyxy"]]
            candidates = [
                (box_iou(bbox, self._tracks[track_id].bbox), track_id)
                for track_id in unused
                if self._tracks[track_id].label == label
            ]
            score, track_id = max(candidates, default=(0.0, -1))
            if score < self.minimum_iou:
                track_id = self._next_id
                self._next_id += 1
                self._tracks[track_id] = _Track(track_id, label, bbox, self._frame)
            else:
                track = self._tracks[track_id]
                track.bbox = bbox
                track.last_frame = self._frame
                track.hits += 1
                unused.discard(track_id)
            item = dict(detection)
            item["track_id"] = track_id
            item["object_id"] = f"{label.replace(' ', '_')}_{track_id:03d}"
            item["track_hits"] = self._tracks[track_id].hits
            output.append(item)

        self._tracks = {
            track_id: track
            for track_id, track in self._tracks.items()
            if self._frame - track.last_frame <= self.maximum_missed
        }
        return output
