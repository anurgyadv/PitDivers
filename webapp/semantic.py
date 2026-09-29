from __future__ import annotations

import json
import re
import shutil
import threading
from html import escape
from pathlib import Path
from typing import Any


REVIEW_STATES = {"candidate", "accepted", "rejected"}


class SemanticStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def load(self, run_folder: Path) -> dict[str, Any]:
        path = run_folder / "objects.json"
        if not path.is_file():
            raise FileNotFoundError("Semantic object registry not found")
        registry = json.loads(path.read_text(encoding="utf-8-sig"))
        registry.setdefault("calibration", None)
        for item in registry.get("objects", []):
            item.setdefault("review", {"status": "candidate", "note": ""})
            item.setdefault("geometry_ids", [item["object_id"]])
        return registry

    def save(self, run_folder: Path, registry: dict[str, Any]) -> dict[str, Any]:
        registry["object_count"] = len(registry.get("objects", []))
        registry["review_summary"] = {
            state: sum(item.get("review", {}).get("status", "candidate") == state for item in registry["objects"])
            for state in sorted(REVIEW_STATES)
        }
        path = run_folder / "objects.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(registry, indent=2), encoding="utf-8")
        temporary.replace(path)
        self._write_report(run_folder, registry)
        return registry

    @staticmethod
    def _write_report(run_folder: Path, registry: dict[str, Any]) -> None:
        rows = []
        evidence = []
        for item in registry.get("objects", []):
            status = item.get("review", {}).get("status", "candidate")
            rows.append(
                f"<tr class='{escape(status)}'><td>{escape(item['object_id'])}</td><td>{escape(item['label'])}</td>"
                f"<td>{escape(status)}</td><td>{float(item['confidence']):.2f}</td>"
                f"<td>{int(item.get('observations', 0))}</td><td>{int(item.get('point_count', 0)):,}</td></tr>"
            )
            masks = item.get("mask_files", [])
            if masks:
                evidence.append(f"<a href='{escape(masks[0])}'><img src='{escape(masks[0])}' alt='{escape(item['object_id'])} mask'><span>{escape(item['object_id'])}</span></a>")
        calibration = registry.get("calibration")
        scale = f"Metric scale: {float(calibration['meters_per_unit']):.4f} metres per scene unit." if calibration else "Scale remains relative until one known dimension is entered in the viewer."
        (run_folder / "report.html").write_text(f"""<!doctype html><meta charset='utf-8'><title>PitDivers semantic review</title>
<style>body{{font:15px system-ui;background:#0b1117;color:#e8eef5;max-width:1100px;margin:40px auto;padding:0 20px}}table{{border-collapse:collapse;width:100%;background:#111b24}}th,td{{padding:10px;border:1px solid #2c3a46;text-align:left}}tr.accepted td:nth-child(3){{color:#45d39a}}tr.rejected{{opacity:.45;text-decoration:line-through}}.evidence{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.evidence a{{position:relative;color:white}}.evidence img{{width:100%;height:150px;object-fit:contain;background:#050709}}.evidence span{{position:absolute;left:6px;bottom:6px;background:#000b;padding:4px}}</style>
<h1>PitDivers semantic review</h1><p>{escape(scale)}</p><p>{registry['review_summary']['accepted']} accepted · {registry['review_summary']['candidate']} to review · {registry['review_summary']['rejected']} rejected</p>
<table><thead><tr><th>Object</th><th>Label</th><th>Status</th><th>Confidence</th><th>Views</th><th>Points</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>Evidence</h2><div class='evidence'>{''.join(evidence)}</div>""", encoding="utf-8")

    def review(self, run_folder: Path, object_id: str, *, status: str, label: str, note: str) -> dict[str, Any]:
        if status not in REVIEW_STATES:
            raise ValueError("Unknown review status")
        label = label.strip()
        if not label:
            raise ValueError("Object label cannot be empty")
        with self._lock:
            registry = self.load(run_folder)
            item = next((candidate for candidate in registry["objects"] if candidate["object_id"] == object_id), None)
            if item is None:
                raise KeyError(object_id)
            item["label"] = label
            item["review"] = {"status": status, "note": note.strip()}
            self.save(run_folder, registry)
            return item

    def calibrate(self, run_folder: Path, object_id: str, axis: int, known_extent_m: float) -> dict[str, Any]:
        if axis not in {0, 1, 2} or known_extent_m <= 0:
            raise ValueError("Choose an axis and enter a positive real-world size")
        with self._lock:
            registry = self.load(run_folder)
            item = next((candidate for candidate in registry["objects"] if candidate["object_id"] == object_id), None)
            if item is None:
                raise KeyError(object_id)
            extent = float(item["bbox_max"][axis]) - float(item["bbox_min"][axis])
            if extent <= 1e-6:
                raise ValueError("The selected object has no measurable extent on that axis")
            objects = [candidate for candidate in registry["objects"] if candidate.get("review", {}).get("status") != "rejected"]
            origin = [min(float(candidate["bbox_min"][index]) for candidate in objects) for index in range(3)]
            calibration = {
                "calibrated": True,
                "meters_per_unit": known_extent_m / extent,
                "reference_object_id": object_id,
                "reference_axis": "xyz"[axis],
                "reference_extent_m": known_extent_m,
                "origin_world": origin,
                "map_axes": {"x": "world_x", "y": "world_z"},
            }
            registry["calibration"] = calibration
            self.save(run_folder, registry)
            return calibration

    def merge(self, run_folder: Path, object_ids: list[str], label: str) -> dict[str, Any]:
        unique_ids = list(dict.fromkeys(object_ids))
        if len(unique_ids) < 2:
            raise ValueError("Select at least two objects to merge")
        with self._lock:
            registry = self.load(run_folder)
            selected = [item for item in registry["objects"] if item["object_id"] in unique_ids]
            if len(selected) != len(unique_ids):
                raise KeyError("One or more objects were not found")
            label = label.strip() or selected[0]["label"]
            prefix = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "object"
            used = {item["object_id"] for item in registry["objects"]}
            number = 1
            while f"{prefix}_{number:04d}" in used:
                number += 1
            weights = [max(int(item.get("point_count", 0)), 1) for item in selected]
            total_weight = sum(weights)
            merged = {
                "object_id": f"{prefix}_{number:04d}",
                "label": label,
                "confidence": sum(float(item["confidence"]) * weight for item, weight in zip(selected, weights)) / total_weight,
                "centroid_world": [sum(float(item["centroid_world"][axis]) * weight for item, weight in zip(selected, weights)) / total_weight for axis in range(3)],
                "bbox_min": [min(float(item["bbox_min"][axis]) for item in selected) for axis in range(3)],
                "bbox_max": [max(float(item["bbox_max"][axis]) for item in selected) for axis in range(3)],
                "point_count": sum(int(item.get("point_count", 0)) for item in selected),
                "observations": sum(int(item.get("observations", 0)) for item in selected),
                "source_frames": sorted({frame for item in selected for frame in item.get("source_frames", [])}),
                "mask_files": list(dict.fromkeys(mask for item in selected for mask in item.get("mask_files", []))),
                "geometry_ids": list(dict.fromkeys(geometry for item in selected for geometry in item.get("geometry_ids", [item["object_id"]]))),
                "surface_support": min(float(item.get("surface_support", 0)) for item in selected),
                "review": {"status": "candidate", "note": f"Merged from {', '.join(unique_ids)}"},
                "merged_from": unique_ids,
            }
            registry["objects"] = [item for item in registry["objects"] if item["object_id"] not in unique_ids] + [merged]
            registry["objects"].sort(key=lambda item: (item["label"], item["object_id"]))
            self.save(run_folder, registry)
            return merged

    def split(self, run_folder: Path, object_id: str, axis: int) -> list[dict[str, Any]]:
        if axis not in {0, 1, 2}:
            raise ValueError("Choose X, Y, or Z for the split")
        import numpy as np
        import trimesh

        from vision.semantic3d.export import export_scene, write_semantic_ply

        with self._lock:
            registry = self.load(run_folder)
            selected = next((item for item in registry["objects"] if item["object_id"] == object_id), None)
            if selected is None:
                raise KeyError(object_id)
            scene = trimesh.load(str(run_folder / "scene.glb"), process=False, force="scene")

            def materialise(item: dict[str, Any]) -> dict[str, Any]:
                point_sets, colour_sets = [], []
                for geometry_id in item.get("geometry_ids", [item["object_id"]]):
                    geometry = scene.geometry.get(geometry_id)
                    if geometry is None:
                        continue
                    point_sets.append(np.asarray(geometry.vertices, dtype=np.float32))
                    colour_sets.append(np.asarray(geometry.colors, dtype=np.uint8)[:, :3])
                if not point_sets:
                    raise ValueError(f"Geometry for {item['object_id']} is unavailable")
                points = np.concatenate(point_sets)
                colours = np.concatenate(colour_sets)
                return {**item, "points": points, "colours": colours, "point_confidence": np.full(len(points), float(item["confidence"]), np.float32)}

            materialised = [materialise(item) for item in registry["objects"]]
            source = next(item for item in materialised if item["object_id"] == object_id)
            coordinates = source["points"][:, axis]
            threshold = float(np.median(coordinates))
            partitions = [coordinates <= threshold, coordinates > threshold]
            if min(int(mask.sum()) for mask in partitions) < 20:
                raise ValueError("That axis does not produce two useful point groups")
            used = {item["object_id"] for item in materialised}
            prefix = re.sub(r"_\d+$", "", object_id)
            children = []
            for mask in partitions:
                number = 1
                while f"{prefix}_{number:04d}" in used:
                    number += 1
                child_id = f"{prefix}_{number:04d}"
                used.add(child_id)
                points = source["points"][mask]
                child = {
                    **source,
                    "object_id": child_id,
                    "geometry_ids": [child_id],
                    "centroid_world": np.median(points, axis=0).tolist(),
                    "bbox_min": np.min(points, axis=0).tolist(),
                    "bbox_max": np.max(points, axis=0).tolist(),
                    "point_count": int(len(points)),
                    "points": points,
                    "colours": source["colours"][mask],
                    "point_confidence": source["point_confidence"][mask],
                    "review": {"status": "candidate", "note": f"Split from {object_id} on world {'XYZ'[axis]}"},
                    "split_from": object_id,
                }
                child.pop("merged_from", None)
                children.append(child)
            rebuilt = [item for item in materialised if item["object_id"] != object_id] + children
            for item in rebuilt:
                item["geometry_ids"] = [item["object_id"]]
            source_scene = run_folder.parent / registry["source_reconstruction"] / "scene.glb"
            if not source_scene.is_file():
                raise ValueError("Source reconstruction is unavailable")
            export_scene(source_scene, run_folder / "semantic_scene.glb", rebuilt)
            shutil.copy2(run_folder / "semantic_scene.glb", run_folder / "scene.glb")
            write_semantic_ply(run_folder / "semantic_points.ply", rebuilt)
            registry["objects"] = [
                {key: value for key, value in item.items() if key not in {"points", "colours", "point_confidence"}}
                for item in rebuilt
            ]
            self.save(run_folder, registry)
            return [{key: value for key, value in item.items() if key not in {"points", "colours", "point_confidence"}} for item in children]
