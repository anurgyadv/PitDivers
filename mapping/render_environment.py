"""Render mapped temperature or humidity samples to a standalone SVG map."""

from __future__ import annotations

import argparse
import html
from pathlib import Path

from records import ScanStore


def render(samples: list[tuple[float, float, float | None, float | None]], field: str) -> str:
    column = 2 if field == "temperature" else 3
    placed = [(x, y, float(row[column])) for row in samples if row[column] is not None
              for x, y in [(row[0], row[1])]]
    if not placed:
        raise ValueError(f"No mapped {field} samples yet. Run the ROS mapper while moving the rover.")
    xs, ys, values = zip(*placed)
    min_x, max_x = min(xs) - 0.5, max(xs) + 0.5
    min_y, max_y = min(ys) - 0.5, max(ys) + 0.5
    low, high = min(values), max(values)
    scale = min(800 / (max_x - min_x), 700 / (max_y - min_y))
    width = int((max_x - min_x) * scale + 140)
    height = int((max_y - min_y) * scale + 150)
    xy = [(70 + (x - min_x) * scale, 90 + (max_y - y) * scale, v) for x, y, v in placed]
    title = "Temperature (°C)" if field == "temperature" else "Humidity (%)"
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="#111820"/>',
             f'<text x="35" y="40" fill="white" font-size="24">PitDivers {html.escape(title)}</text>',
             f'<text x="35" y="65" fill="#aab" font-size="14">{len(placed)} placed scans · {low:.1f}–{high:.1f}</text>']
    route = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in xy)
    lines.append(f'<polyline points="{route}" fill="none" stroke="#718096" stroke-width="2" opacity=".65"/>')
    for x, y, value in xy:
        t = (value - low) / (high - low) if high > low else 0.5
        red = round(60 + 195 * t)
        blue = round(255 - 205 * t)
        colour = f"#{red:02x}50{blue:02x}"
        lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="{colour}" opacity=".8"><title>{value:.1f} at ({min_x+(x-70)/scale:.2f}, {max_y-(y-90)/scale:.2f}) m</title></circle>')
    lines += [f'<text x="35" y="{height-25}" fill="#aab" font-size="14">x: {min_x:.1f} to {max_x:.1f} m · y: {min_y:.1f} to {max_y:.1f} m</text>', '</svg>']
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="mapping/room_scans.sqlite3")
    parser.add_argument("--field", choices=("temperature", "humidity"), default="temperature")
    parser.add_argument("--out", default="mapping/environment.svg")
    args = parser.parse_args()
    store = ScanStore(args.db)
    try:
        svg = render(store.placed_environment(), args.field)
    finally:
        store.close()
    Path(args.out).write_text(svg, encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
