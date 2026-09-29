from __future__ import annotations

import json
import shutil
import struct
from pathlib import Path

import numpy as np
import trimesh


PALETTE = np.array([
    [255, 79, 94, 255], [72, 202, 228, 255], [255, 190, 11, 255], [131, 56, 236, 255],
    [6, 214, 160, 255], [251, 86, 7, 255], [58, 134, 255, 255], [255, 0, 110, 255],
], dtype=np.uint8)


def read_glb_alignment(path: Path) -> np.ndarray:
    with path.open("rb") as handle:
        handle.read(12)
        json_length, _ = struct.unpack("<II", handle.read(8))
        payload = json.loads(handle.read(json_length).decode("utf-8").rstrip(" \x00"))
    value = payload.get("scenes", [{}])[0].get("extras", {}).get("hf_alignment")
    return np.asarray(value if value is not None else np.eye(4), dtype=np.float32)


def write_semantic_ply(path: Path, objects: list[dict]) -> None:
    records = []
    for object_index, item in enumerate(objects):
        colour = PALETTE[object_index % len(PALETTE), :3]
        for point, confidence in zip(item["points"], item["point_confidence"]):
            records.append((*point, *colour, object_index, float(confidence)))
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(records)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "property int object_id\nproperty float confidence\nend_header\n"
    ).encode("ascii")
    with path.open("wb") as handle:
        handle.write(header)
        for record in records:
            handle.write(struct.pack("<fffBBBi f".replace(" ", ""), *record))


def export_scene(base_scene: Path, destination: Path, objects: list[dict]) -> None:
    scene = trimesh.load(str(base_scene), process=False, force="scene")
    for index, item in enumerate(objects):
        colour = np.repeat(PALETTE[index % len(PALETTE)][None, :], len(item["points"]), axis=0)
        cloud = trimesh.points.PointCloud(item["points"], colors=colour)
        scene.add_geometry(cloud, node_name=item["object_id"], geom_name=item["object_id"])
    destination.write_bytes(scene.export(file_type="glb"))
    _name_glb_materials(destination)


def _name_glb_materials(path: Path) -> None:
    """Name each point material after its node so the web viewer can highlight it."""
    blob = path.read_bytes()
    _, version, _ = struct.unpack_from("<4sII", blob, 0)
    chunks = []
    offset = 12
    while offset < len(blob):
        length, chunk_type = struct.unpack_from("<II", blob, offset)
        chunks.append([chunk_type, blob[offset + 8:offset + 8 + length]])
        offset += 8 + length
    for chunk in chunks:
        if chunk[0] != 0x4E4F534A:
            continue
        document = json.loads(chunk[1].decode("utf-8").rstrip(" \x00"))
        materials = document.get("materials", [])
        for node in document.get("nodes", []):
            mesh_index = node.get("mesh")
            if mesh_index is None:
                continue
            for primitive in document.get("meshes", [])[mesh_index].get("primitives", []):
                material_index = primitive.get("material")
                if material_index is not None and material_index < len(materials):
                    materials[material_index]["name"] = node.get("name", f"material_{material_index}")
                    if material_index:
                        materials[material_index]["alphaMode"] = "BLEND"
        payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
        chunk[1] = payload + b" " * ((-len(payload)) % 4)
    total_length = 12 + sum(8 + len(payload) for _, payload in chunks)
    output = bytearray(struct.pack("<4sII", b"glTF", version, total_length))
    for chunk_type, payload in chunks:
        output.extend(struct.pack("<II", len(payload), chunk_type))
        output.extend(payload)
    path.write_bytes(output)


def write_registry(path: Path, source_run: str, classes: list[str], objects: list[dict]) -> None:
    clean = []
    for item in objects:
        clean.append({key: value for key, value in item.items() if key not in {"points", "colours", "point_confidence"}})
    path.write_text(json.dumps({
        "schema_version": "1.0",
        "source_reconstruction": source_run,
        "vocabulary": classes,
        "object_count": len(clean),
        "objects": clean,
    }, indent=2))


def copy_base_scene(source: Path, destination: Path) -> None:
    shutil.copy2(source, destination)
