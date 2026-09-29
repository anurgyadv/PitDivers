from __future__ import annotations

import html
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

from .export import PALETTE, export_scene, read_glb_alignment, write_registry, write_semantic_ply
from .fusion import Observation, fuse_observations
from .projection import apply_transform, project_mask
from .surface import anchor_objects_to_scene


DEFAULT_CLASSES = [
    "coffee machine", "table", "chair", "door", "cabinet", "box", "bag", "bottle",
    "electrical outlet", "light switch", "cable", "person",
]


def _load_yoloe(project_root: Path, classes: list[str]):
    sys.path[:0] = [str(project_root / ".semantic_deps"), str(project_root / "vision/.venv/Lib/site-packages")]
    from ultralytics import YOLOE
    model = YOLOE(str(project_root / "yoloe-26s-seg.pt"))
    model.set_classes(classes, model.get_text_pe(classes))
    return model


def _write_report(path: Path, objects: list[dict], debug_files: list[str]) -> None:
    rows = "".join(
        f"<tr><td>{html.escape(item['object_id'])}</td><td>{html.escape(item['label'])}</td>"
        f"<td>{item['confidence']:.2f}</td><td>{item['observations']}</td><td>{item['point_count']:,}</td></tr>"
        for item in objects
    )
    images = "".join(f"<img src='{html.escape(name)}' alt='Detection preview'>" for name in debug_files)
    path.write_text(f"""<!doctype html><meta charset='utf-8'><title>PitDivers semantic reconstruction</title>
<style>body{{font:15px system-ui;background:#0b1117;color:#e8eef5;max-width:1100px;margin:40px auto;padding:0 20px}}h1{{font-size:28px}}table{{border-collapse:collapse;width:100%;background:#111b24}}th,td{{padding:10px;border:1px solid #2c3a46;text-align:left}}img{{width:31%;margin:1%;border-radius:6px}}</style>
<h1>PitDivers semantic reconstruction</h1><p>{len(objects)} persistent object candidates. Confidence is model evidence, not calibrated real-world probability.</p>
<table><thead><tr><th>Object</th><th>Class</th><th>Confidence</th><th>Views</th><th>Points</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Detection samples</h2>{images}""")


def run(source_run: Path, output_dir: Path, classes: list[str] | None = None) -> dict:
    classes = classes or DEFAULT_CLASSES
    project_root = Path(__file__).resolve().parents[2]
    npz_path = source_run / "exports/npz/results.npz"
    base_glb = source_run / "scene.glb"
    output_dir.mkdir(parents=True, exist_ok=True)
    masks_dir = output_dir / "masks"
    detections_dir = output_dir / "detections"
    debug_dir = output_dir / "debug"
    for folder in (masks_dir, detections_dir, debug_dir):
        folder.mkdir(exist_ok=True)

    data = np.load(npz_path)
    images = data["image"]
    depths, depth_conf = data["depth"], data["conf"]
    intrinsics, extrinsics = data["intrinsics"], data["extrinsics"]
    alignment = read_glb_alignment(base_glb)
    model = _load_yoloe(project_root, classes)
    observations: list[Observation] = []
    debug_files = []

    for frame_id, rgb in enumerate(images):
        result = model.predict(rgb[:, :, ::-1], conf=0.16, imgsz=640, device=0, verbose=False)[0]
        frame_records = []
        preview = rgb.copy()
        if result.masks is not None:
            masks = result.masks.data.cpu().numpy()
            for detection_index, (box, raw_mask) in enumerate(zip(result.boxes, masks)):
                class_id = int(box.cls.item())
                label = classes[class_id]
                detection_confidence = float(box.conf.item())
                mask = cv2.resize(raw_mask, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR) >= 0.5
                if mask.sum() < 20:
                    continue
                mask_name = f"frame_{frame_id:04d}_{detection_index:02d}.png"
                cv2.imwrite(str(masks_dir / mask_name), mask.astype(np.uint8) * 255)
                points, confidence, pixels = project_mask(
                    mask, depths[frame_id], depth_conf[frame_id], intrinsics[frame_id], extrinsics[frame_id],
                    detection_confidence, erosion_pixels=1, confidence_percentile=35, max_points=3000,
                )
                if len(points) < 20:
                    continue
                points = apply_transform(points, alignment)
                colours = rgb[pixels[:, 1], pixels[:, 0]]
                observations.append(Observation(label, frame_id, detection_confidence, points, colours, confidence, f"masks/{mask_name}"))
                frame_records.append({
                    "class": label, "confidence": detection_confidence, "mask": f"masks/{mask_name}",
                    "projected_points": len(points), "bbox_xyxy": box.xyxy[0].cpu().tolist(),
                })
                overlay_colour = PALETTE[class_id % len(PALETTE), :3]
                preview[mask] = (0.55 * preview[mask] + 0.45 * overlay_colour).astype(np.uint8)
        (detections_dir / f"frame_{frame_id:04d}.json").write_text(json.dumps({"frame": frame_id, "detections": frame_records}, indent=2))
        if frame_id % 8 == 0:
            name = f"debug/frame_{frame_id:04d}.jpg"
            cv2.imwrite(str(output_dir / name), preview[:, :, ::-1])
            debug_files.append(name)
        print(f"Frame {frame_id + 1}/{len(images)}: {len(frame_records)} accepted", flush=True)

    objects = anchor_objects_to_scene(base_glb, fuse_observations(observations))
    write_registry(output_dir / "objects.json", source_run.name, classes, objects)
    write_semantic_ply(output_dir / "semantic_points.ply", objects)
    export_scene(base_glb, output_dir / "semantic_scene.glb", objects)
    shutil.copy2(output_dir / "semantic_scene.glb", output_dir / "scene.glb")
    _write_report(output_dir / "report.html", objects, debug_files)
    summary = {
        "status": "complete", "source_run": source_run.name, "frames": len(images),
        "accepted_observations": len(observations), "objects": len(objects),
        "outputs": ["scene.glb", "semantic_scene.glb", "objects.json", "semantic_points.ply", "report.html", "detections", "masks", "debug"],
    }
    (output_dir / "semantic_manifest.json").write_text(json.dumps(summary, indent=2))
    return summary
