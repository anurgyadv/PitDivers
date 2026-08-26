"""Start the dashboard with either the project venv or Codex's bundled Python."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_PACKAGES = PROJECT_ROOT / "vision" / ".venv" / "Lib" / "site-packages"
DA3_SOURCE = PROJECT_ROOT / "third_party" / "depth-anything-3" / "src"

for dependency_path in (PROJECT_ROOT, VENV_PACKAGES, DA3_SOURCE):
    value = str(dependency_path)
    if dependency_path.exists() and value not in sys.path:
        sys.path.insert(0, value)

from webapp.__main__ import main


if __name__ == "__main__":
    main()

