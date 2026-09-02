#!/usr/bin/env python3
"""Generate STL files from the rover model, mirroring hardware/rover.scad.

Produces printable parts as watertight solids (boolean unions/differences via
the manifold3d backend) and the full assembly as a combined preview mesh.

    python3 hardware/build_stl.py            # writes STLs into hardware/stl/

Requires: trimesh, manifold3d, numpy  (pip install trimesh manifold3d numpy)
"""
import os
import numpy as np
import trimesh
from trimesh.creation import box as _box, cylinder as _cyl
from trimesh.transformations import rotation_matrix, translation_matrix

# ---- parameters (kept in sync with rover.scad) ------------------------------
wall, clear = 2.4, 0.4
plate_hole_d = 3.2
# HC-SR04
sr04_pcb_l, sr04_pcb_h, sr04_pcb_t = 45, 20, 1.6
sr04_can_d, sr04_can_h, sr04_can_gap = 16, 12, 26
# DHT11
dht_pcb_l, dht_pcb_w, dht_pcb_t = 20.5, 15.5, 1.2
dht_body_l, dht_body_w, dht_body_h = 12, 16, 5.5
# MPU6050
mpu_pcb_l, mpu_pcb_w, mpu_pcb_t = 21.2, 15.6, 1.6
# ESP32-S3 cam
cam_pcb_l, cam_pcb_w, cam_pcb_t, cam_lens_d = 41, 24.5, 1.6, 8.5
# chassis
deck_len, deck_wid, deck_thick, deck_gap = 200, 105, 3, 45
wheel_d, wheel_w, hub_d, wheelbase = 65, 27, 20, 120
motor_l, motor_w, motor_h = 70, 22.5, 18.6

SEG = 64  # cylinder facets


def box_c(size, corner):
    """OpenSCAD cube(size, center=false) at min-corner `corner`."""
    m = _box(extents=size)
    m.apply_translation(np.array(corner) + np.array(size) / 2.0)
    return m


def box_ctr(size, center):
    m = _box(extents=size)
    m.apply_translation(center)
    return m


def cyl_z(d, h, center=(0, 0, 0), base=False):
    """Cylinder along +Z. base=True puts its bottom at center[2] (OpenSCAD)."""
    m = _cyl(radius=d / 2.0, height=h, sections=SEG)
    z = center[2] + (h / 2.0 if base else 0.0)
    m.apply_translation([center[0], center[1], z])
    return m


def cyl_y(d, h, center):
    """Cylinder centred at `center` with its axis along Y."""
    m = _cyl(radius=d / 2.0, height=h, sections=SEG)
    m.apply_transform(rotation_matrix(np.pi / 2.0, [1, 0, 0]))
    m.apply_translation(center)
    return m


def cyl_x(d, h, base_x, y, z):
    """Cylinder axis along +X, bottom face at x=base_x."""
    m = _cyl(radius=d / 2.0, height=h, sections=SEG)
    m.apply_transform(rotation_matrix(np.pi / 2.0, [0, 1, 0]))
    m.apply_translation([base_x + h / 2.0, y, z])
    return m


# ---- printable parts --------------------------------------------------------
def sensor_bracket():
    base_l = sr04_pcb_l + 2 * wall + 2 * clear
    base_w = 26
    face_h = sr04_pcb_h + wall
    slot_w = sr04_pcb_t + 2 * clear

    parts = [
        box_c([base_l, base_w, wall], [-base_l / 2, -base_w / 2, 0]),
        box_c([base_l, wall, face_h], [-base_l / 2, base_w / 2 - wall, 0]),
    ]
    for sx in (-1, 1):
        x = sx * (sr04_can_gap / 2 + sr04_can_d / 2 + slot_w)
        parts.append(box_c([wall, slot_w + wall, face_h],
                           [x, base_w / 2 - wall - slot_w, 0]))
    solid = trimesh.boolean.union(parts)

    cuts = []
    for sy in (-1, 1):
        cuts.append(cyl_y(sr04_can_d + clear, 3 * wall,
                          [sy * sr04_can_gap / 2, base_w / 2 + wall, sr04_pcb_h / 2]))
    for sx in (-1, 1):
        cuts.append(cyl_z(plate_hole_d, wall + 1,
                          center=[sx * (base_l / 2 - 6), -base_w / 2 + 6, -0.5], base=True))
    return trimesh.boolean.difference([solid] + cuts)


def camera_mount():
    post_h, tilt = 30, np.radians(10)
    shelf_l = cam_pcb_l + 2 * wall
    shelf_w = cam_pcb_w + 2 * wall

    foot = box_c([shelf_w, shelf_l, wall], [-shelf_w / 2, -shelf_l / 2, 0])
    post = box_c([12, wall, post_h], [-6, -shelf_l / 2, 0])

    shelf = box_c([shelf_w, shelf_l, wall], [-shelf_w / 2, 0, 0])
    hole = cyl_z(cam_lens_d + 1, wall + 1, center=[0, shelf_l - 12, -0.5], base=True)
    shelf = trimesh.boolean.difference([shelf, hole])
    T = translation_matrix([0, -shelf_l / 2 + wall, post_h]) @ rotation_matrix(tilt, [1, 0, 0])
    shelf.apply_transform(T)

    return trimesh.boolean.union([foot, post, shelf])


# ---- full assembly (combined preview mesh, not booleaned) -------------------
def assembly():
    m = []
    lower_z = wheel_d / 2
    upper_z = lower_z + deck_thick + deck_gap
    for z in (lower_z, upper_z):
        m.append(box_ctr([deck_len, deck_wid, deck_thick], [0, 0, z + deck_thick / 2]))
    for sx in (-1, 1):
        for sy in (-1, 1):
            m.append(cyl_z(6, deck_gap,
                     center=[sx * (deck_len / 2 - 12), sy * (deck_wid / 2 - 12),
                             lower_z + deck_thick], base=True))
    for ax in (-1, 1):
        for sy in (-1, 1):
            m.append(box_ctr([motor_l, motor_w, motor_h],
                     [ax * wheelbase / 2, sy * (deck_wid / 2 - motor_w / 2 - 2),
                      lower_z - motor_h / 2 - 1]))
            m.append(cyl_y(wheel_d, wheel_w,
                     [ax * wheelbase / 2, sy * (deck_wid / 2 + wheel_w / 2 + 3), wheel_d / 2]))
    # sensors
    m.append(box_ctr([sr04_pcb_t, sr04_pcb_l, sr04_pcb_h],
             [deck_len / 2 - 4, 0, lower_z + deck_thick + sr04_pcb_h / 2 + 1]))
    for sy in (-1, 1):
        m.append(cyl_x(sr04_can_d, sr04_can_h, deck_len / 2 - 4,
                 sy * sr04_can_gap / 2, lower_z + deck_thick + sr04_pcb_h / 2 + 1))
    m.append(box_ctr([dht_pcb_l, dht_pcb_w, dht_pcb_t],
             [-deck_len / 2 + 30, deck_wid / 2 - 20, upper_z + deck_thick]))
    m.append(box_ctr([mpu_pcb_l, mpu_pcb_w, mpu_pcb_t],
             [0, -deck_wid / 2 + 20, upper_z + deck_thick]))
    m.append(box_ctr([cam_pcb_w, cam_pcb_l, cam_pcb_t],
             [deck_len / 2 - 20, 0, upper_z + deck_thick + 34]))
    # brackets in place
    b = sensor_bracket(); b.apply_translation([deck_len / 2 - 4, 0, lower_z + deck_thick]); m.append(b)
    c = camera_mount(); c.apply_translation([deck_len / 2 - 20, 0, upper_z + deck_thick]); m.append(c)
    return trimesh.util.concatenate(m)


def main():
    out = os.path.join(os.path.dirname(__file__), "stl")
    os.makedirs(out, exist_ok=True)
    for name, fn in [("sensor_bracket", sensor_bracket),
                     ("camera_mount", camera_mount),
                     ("rover_assembly", assembly)]:
        mesh = fn()
        path = os.path.join(out, name + ".stl")
        mesh.export(path)
        print(f"{name:16s} {len(mesh.faces):6d} faces  watertight={mesh.is_watertight}  -> {path}")


if __name__ == "__main__":
    main()
