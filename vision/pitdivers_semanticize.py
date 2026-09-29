from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for dependency in (ROOT, ROOT / ".semantic_deps", ROOT / "vision/.venv/Lib/site-packages"):
    if str(dependency) not in sys.path:
        sys.path.insert(0, str(dependency))

from vision.semantic3d.pipeline import run


def read_classes(path: Path) -> list[str]:
    classes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            classes.append(stripped[2:].strip())
    if not classes:
        raise ValueError(f"No classes found in {path}")
    return classes


def main() -> None:
    parser = argparse.ArgumentParser(description="Transfer YOLOE image masks into a DA3 reconstruction")
    parser.add_argument("source_run", type=Path, help="DA3 run containing scene.glb and exports/npz/results.npz")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--classes", type=Path, default=ROOT / "vision/classes.yaml")
    args = parser.parse_args()
    print(json.dumps(run(args.source_run.resolve(), args.output.resolve(), read_classes(args.classes.resolve())), indent=2))


if __name__ == "__main__":
    main()
