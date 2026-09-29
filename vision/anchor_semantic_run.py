from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for dependency in (ROOT, ROOT / ".semantic_deps", ROOT / "vision/.venv/Lib/site-packages"):
    sys.path.insert(0, str(dependency))

import trimesh

from vision.semantic3d.export import export_scene, write_registry, write_semantic_ply
from vision.semantic3d.pipeline import _write_report
from vision.semantic3d.surface import anchor_objects_to_scene


def repair(source_run: Path, semantic_run: Path) -> dict:
    registry_path = semantic_run / "objects.json"
    registry = json.loads(registry_path.read_text())
    semantic_scene = trimesh.load(str(semantic_run / "scene.glb"), process=False, force="scene")
    objects = []
    for item in registry["objects"]:
        geometry = semantic_scene.geometry.get(item["object_id"])
        if geometry is None:
            continue
        points = np.asarray(geometry.vertices, dtype=np.float32)
        colours = np.asarray(geometry.colors)[:, :3]
        objects.append({
            **item,
            "points": points,
            "colours": colours,
            "point_confidence": np.full(len(points), item["confidence"], dtype=np.float32),
        })
    objects = anchor_objects_to_scene(source_run / "scene.glb", objects)
    write_registry(registry_path, registry["source_reconstruction"], registry["vocabulary"], objects)
    write_semantic_ply(semantic_run / "semantic_points.ply", objects)
    export_scene(source_run / "scene.glb", semantic_run / "semantic_scene.glb", objects)
    shutil.copy2(semantic_run / "semantic_scene.glb", semantic_run / "scene.glb")
    debug_files = [f"debug/{path.name}" for path in sorted((semantic_run / "debug").glob("*.jpg"))]
    _write_report(semantic_run / "report.html", objects, debug_files)
    manifest_path = semantic_run / "semantic_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["objects"] = len(objects)
    manifest["surface_anchored"] = True
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return {"objects": len(objects), "surface_anchored": True}


def main() -> None:
    parser = argparse.ArgumentParser(description="Snap a semantic run onto its reconstructed surface")
    parser.add_argument("source_run", type=Path)
    parser.add_argument("semantic_run", type=Path)
    args = parser.parse_args()
    print(json.dumps(repair(args.source_run.resolve(), args.semantic_run.resolve()), indent=2))


if __name__ == "__main__":
    main()
