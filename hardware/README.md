# PitDivers Rover — 3D Model

A parametric CAD model of the PitDivers rover, built in
[OpenSCAD](https://openscad.org). It models the Freenove FNK0082 4WD ESP32-S3
car and everything mounted on it: the ESP32-S3 camera, HC-SR04 ultrasonic
sensor, DHT11 temperature/humidity sensor, and MPU6050 IMU.

It serves two jobs from one source file:

1. **Visualisation / digital twin** — the full `assembly` shows how the rover
   goes together and where each sensor sits.
2. **3D printing** — the custom brackets (`sensor_bracket`, `camera_mount`)
   are the parts you actually print. The chassis, wheels and sensor boards are
   off-the-shelf, so they're modelled for reference but aren't meant to be
   printed.

## Files

| File | Purpose |
|---|---|
| `rover.scad` | The complete parametric model. All dimensions live at the top. |
| `build_stl.py` | Exports STLs without OpenSCAD (mirrors the same dimensions). |
| `stl/` | Generated STL meshes (regenerate with `build_stl.py`; not tracked). |

## Quick STL export without OpenSCAD

If you don't have OpenSCAD handy, `build_stl.py` reproduces the same parts with
[`trimesh`](https://trimesh.org) and writes STLs into `hardware/stl/`:

```bash
pip install trimesh manifold3d numpy
python3 hardware/build_stl.py
```

The two printable brackets come out as watertight solids; the assembly is a
combined preview mesh. For anything you plan to tweak dimensionally, prefer
editing `rover.scad` and exporting from OpenSCAD — that file is the source of
truth.

## Rendering and exporting

Open `rover.scad` in the OpenSCAD GUI and press **F5** (preview) or **F6**
(full render), then **File → Export → Export as STL**.

Or render headless from the command line, choosing the part with `PART`:

```bash
# full rover, for viewing
openscad -o rover_assembly.stl -D 'PART="assembly"' rover.scad

# the printable parts
openscad -o sensor_bracket.stl  -D 'PART="sensor_bracket"' rover.scad
openscad -o camera_mount.stl    -D 'PART="camera_mount"'   rover.scad

# a single deck plate (e.g. as a laser-cut reference)
openscad -o deck_plate.stl      -D 'PART="deck_plate"'     rover.scad
```

You can also set `PART` directly in the file (the `PART = "assembly";` line
near the bottom).

## Making it accurate to *your* build

Every dimension is a named variable in the `PARAMETERS` section of
`rover.scad`. Change a number, re-render — nothing is hard-coded in the
geometry.

Two tags flag how trustworthy each default is:

- **`[DATASHEET]`** — taken from the part's datasheet; accurate as-is.
- **`[VERIFY]`** — a Freenove-typical default. **Measure your own chassis and
  correct these**, because kit revisions vary.

The values most worth measuring on your rover:

| Variable | Meaning | Default | Source |
|---|---|---|---|
| `deck_len`, `deck_wid` | Acrylic plate size | 200 × 105 mm | `[VERIFY]` |
| `deck_gap` | Gap between the two decks | 45 mm | `[VERIFY]` |
| `wheelbase` | Front-to-rear axle distance | 120 mm | `[VERIFY]` |
| `wheel_d`, `wheel_w` | Wheel size | 65 × 27 mm | `[DATASHEET]` |
| `sr04_*` | HC-SR04 board + transducers | 45 × 20 mm, 16 mm cans @ 26 mm | `[DATASHEET]` |
| `dht_*` | DHT11 module | 20.5 × 15.5 mm | `[DATASHEET]` |
| `mpu_*` | MPU6050 (GY-521) | 21.2 × 15.6 mm | `[DATASHEET]` |
| `cam_pcb_l`, `cam_pcb_w` | ESP32-S3 cam board | 41 × 24.5 mm | `[VERIFY]` |

If you send me real measurements or photos of your specific chassis, I'll fold
the exact numbers in.

## Printing notes (custom parts)

Both printable brackets are designed to print without supports on an FDM
printer:

- **`sensor_bracket`** — prints flat on its base; the HC-SR04 slots into the
  upright face with the transducers poking through the two windows. DHT11 sits
  on the base beside it.
- **`camera_mount`** — prints upright; the shelf is tilted ~10° downward so the
  camera looks slightly toward the ground ahead of the rover.

Suggested settings: 0.2 mm layers, 3 perimeters, 20 % infill, PLA or PETG.
Fit clearances are controlled by `bracket_clear` (0.4 mm) — increase it if your
printer runs tight, decrease it for a snugger grip.

## Hardware reference

Pin assignments and wiring for these sensors are documented in
[`firmware/PitDivers_Camera_DHT11/README.md`](../firmware/PitDivers_Camera_DHT11/README.md).
