"""Live polar plot for the PitDivers Freenove LDS02RR scan endpoint.

Run: python tools/plot_lidar.py --url http://ROVER_IP
Install plotting dependency first: python -m pip install matplotlib
Start the LiDAR from the rover's web page before running this script.
"""

from __future__ import annotations

import argparse
import json
import math
from urllib.error import URLError
from urllib.request import urlopen


def get_json(url: str) -> object:
    with urlopen(url, timeout=2) as response:
        return json.load(response)


def scan_points(scan: object, max_mm: int) -> list[tuple[float, float]]:
    """Return (angle in radians, distance in metres) for valid samples."""
    if not isinstance(scan, list) or len(scan) != 360:
        raise ValueError("LiDAR scan must contain exactly 360 distances")
    points = []
    for angle, value in enumerate(scan):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Invalid distance at angle {angle}")
        if 0 < value <= max_mm:
            points.append((math.radians(angle), value / 1000.0))
    return points


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot live PitDivers LiDAR distance data")
    parser.add_argument("--url", required=True, help="Rover address, e.g. http://192.168.1.50")
    parser.add_argument("--max-m", type=float, default=6.0, help="Plot radius in metres (default: 6)")
    parser.add_argument("--interval-ms", type=int, default=500, help="Refresh period (default: 500)")
    args = parser.parse_args()
    if args.max_m <= 0 or args.interval_ms < 100:
        parser.error("--max-m must be positive and --interval-ms must be at least 100")

    # Import here so --help and data validation remain usable without matplotlib.
    try:
        import matplotlib.pyplot as plt
        from matplotlib.animation import FuncAnimation
    except ImportError as exc:
        raise SystemExit("Install matplotlib: python -m pip install matplotlib") from exc

    base_url = args.url.rstrip("/")
    max_mm = int(args.max_m * 1000)
    fig, ax = plt.subplots(subplot_kw={"projection": "polar"})
    fig.canvas.manager.set_window_title("PitDivers LiDAR")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_ylim(0, args.max_m)
    ax.set_rlabel_position(135)
    ax.grid(True)
    dots = ax.scatter([], [], s=12, c="#1688e8")
    title = ax.set_title("Connecting to LiDAR…", pad=20)

    def refresh(_frame: int) -> None:
        try:
            status = get_json(base_url + "/api/lidar/status")
            scan = get_json(base_url + "/api/lidar/scan")
            if not isinstance(status, dict):
                raise ValueError("Invalid LiDAR status")
            points = scan_points(scan, max_mm)
            # Matplotlib expects an Nx2 shape even when there are no points.
            dots.set_offsets(points or [(math.nan, math.nan)])
            state = "running" if status.get("running") else "stopped"
            title.set_text(
                f"LiDAR {state} | {status.get('rpm', 0)} RPM | "
                f"{len(points)} visible points | {status.get('good', 0)} valid packets"
            )
        except (URLError, TimeoutError, ValueError, OSError) as exc:
            title.set_text(f"Waiting for rover: {exc}")

    animation = FuncAnimation(fig, refresh, interval=args.interval_ms, cache_frame_data=False)
    # Hold a reference so the animation survives until the window closes.
    _ = animation
    plt.show()


if __name__ == "__main__":
    main()
