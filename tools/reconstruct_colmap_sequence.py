"""Build a sparse COLMAP reconstruction from an ordered image sequence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pycolmap


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("images", type=Path, help="Directory containing ordered frames")
    parser.add_argument("output", type=Path, help="Output directory")
    parser.add_argument("--max-image-size", type=int, default=1200)
    parser.add_argument("--overlap", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    images = args.images.resolve()
    output = args.output.resolve()
    database = output / "database.db"
    sparse = output / "sparse"

    if not images.is_dir():
        raise FileNotFoundError(images)
    if database.exists() or sparse.exists():
        raise FileExistsError(f"Refusing to overwrite an existing reconstruction in {output}")

    output.mkdir(parents=True, exist_ok=True)
    sparse.mkdir()

    reader = pycolmap.ImageReaderOptions()
    reader.camera_model = "SIMPLE_RADIAL"

    extraction = pycolmap.FeatureExtractionOptions()
    extraction.max_image_size = args.max_image_size
    extraction.sift.max_num_features = 8192

    pycolmap.extract_features(
        database,
        images,
        camera_mode=pycolmap.CameraMode.SINGLE,
        reader_options=reader,
        extraction_options=extraction,
        device=pycolmap.Device.cpu,
    )

    pairing = pycolmap.SequentialPairingOptions()
    pairing.overlap = args.overlap
    pairing.quadratic_overlap = True
    pycolmap.match_sequential(database, pairing_options=pairing, device=pycolmap.Device.cpu)

    reconstructions = pycolmap.incremental_mapping(database, images, sparse)
    if not reconstructions:
        raise RuntimeError("COLMAP could not initialize a reconstruction")

    best_index, best = max(reconstructions.items(), key=lambda item: item[1].num_reg_images())
    best_dir = sparse / str(best_index)
    sparse_cloud = output / "sparse_points.ply"
    best.export_PLY(sparse_cloud)
    summary = {
        "images": str(images),
        "database": str(database),
        "model": str(best_dir),
        "sparse_cloud": str(sparse_cloud),
        "registered_images": best.num_reg_images(),
        "input_images": len(list(images.glob("*"))),
        "points3D": best.num_points3D(),
        "mean_observations_per_image": best.compute_mean_observations_per_reg_image(),
        "mean_track_length": best.compute_mean_track_length(),
        "mean_reprojection_error_px": best.compute_mean_reprojection_error(),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
