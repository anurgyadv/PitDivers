import sys, os
sys.path.insert(0, "/home/user/PitDivers/hardware")
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import build_stl as B

OUT = "/home/user/PitDivers/hardware/renders"
os.makedirs(OUT, exist_ok=True)

BG = "#0e1116"
INK = "#e9edf2"
AMBER = np.array([0.918, 0.482, 0.184])   # printed part
SLATE = np.array([0.62, 0.68, 0.74])      # reference assembly
LIGHT = np.array([0.4, -0.7, 0.8]); LIGHT = LIGHT / np.linalg.norm(LIGHT)


def view_dir(elev, azim):
    el, az = np.radians(elev), np.radians(azim)
    return np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])


def shade(mesh, base, elev, azim):
    tris = mesh.triangles                       # (N,3,3)
    n = mesh.face_normals
    # back-face cull: keep only triangles facing the camera so the solid
    # reads as solid (matplotlib has no depth buffer)
    front = (n @ view_dir(elev, azim)) > -0.02
    tris, n = tris[front], n[front]
    inten = 0.30 + 0.70 * np.clip(n @ LIGHT, 0, 1)
    cols = np.clip(base[None, :] * inten[:, None], 0, 1)
    return tris, cols


def render(mesh, base, fname, elev=24, azim=-58, title=None, sub=None):
    tris, cols = shade(mesh, base, elev, azim)
    fig = plt.figure(figsize=(7.5, 6), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor(BG)
    pc = Poly3DCollection(tris, facecolors=cols, edgecolors=(1, 1, 1, 0.05), linewidths=0.15)
    ax.add_collection3d(pc)

    v = mesh.vertices
    mins, maxs = v.min(0), v.max(0)
    ctr = (mins + maxs) / 2
    span = (maxs - mins).max() * 0.55
    ax.set_xlim(ctr[0] - span, ctr[0] + span)
    ax.set_ylim(ctr[1] - span, ctr[1] + span)
    ax.set_zlim(ctr[2] - span, ctr[2] + span)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    try:
        ax.set_proj_type("persp", focal_length=0.9)
    except Exception:
        pass

    if title:
        fig.text(0.06, 0.93, title, color=INK, fontsize=16,
                 family="monospace", weight="bold")
    if sub:
        fig.text(0.06, 0.89, sub, color="#8c98a7", fontsize=10, family="monospace")
    fig.text(0.94, 0.04, "PitDivers · FNK0082 · mm", color="#5c6672",
             fontsize=8, family="monospace", ha="right")

    fig.savefig(os.path.join(OUT, fname), facecolor=BG, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print("wrote", fname)


asm = B.assembly()
brk = B.sensor_bracket()
cam = B.camera_mount()

render(asm, SLATE, "01_assembly_iso.png", elev=22, azim=-58,
       title="FULL ASSEMBLY", sub="Freenove 4WD + payload · view only")
render(asm, SLATE, "02_assembly_front.png", elev=14, azim=-108,
       title="ASSEMBLY / FRONT", sub="HC-SR04 + camera mast forward")
render(brk, AMBER, "03_sensor_bracket.png", elev=26, azim=-52,
       title="SENSOR BRACKET", sub="HC-SR04 + DHT11 · printable · watertight")
render(cam, AMBER, "04_camera_mount.png", elev=24, azim=-62,
       title="CAMERA MOUNT", sub="ESP32-S3 cam · 10° tilt · printable")


# contact sheet of the two printable parts
def sheet():
    fig = plt.figure(figsize=(11, 4.6), dpi=200)
    fig.patch.set_facecolor(BG)
    for i, (m, nm) in enumerate([(brk, "SENSOR BRACKET"), (cam, "CAMERA MOUNT")]):
        tris, cols = shade(m, AMBER, 24, -56)
        ax = fig.add_subplot(1, 2, i + 1, projection="3d")
        ax.set_facecolor(BG)
        ax.add_collection3d(Poly3DCollection(tris, facecolors=cols,
                            edgecolors=(1, 1, 1, 0.05), linewidths=0.15))
        v = m.vertices; mn, mx = v.min(0), v.max(0); c = (mn + mx) / 2
        s = (mx - mn).max() * 0.55
        ax.set_xlim(c[0]-s, c[0]+s); ax.set_ylim(c[1]-s, c[1]+s); ax.set_zlim(c[2]-s, c[2]+s)
        ax.set_box_aspect((1, 1, 1)); ax.view_init(elev=24, azim=-56); ax.set_axis_off()
        ax.text2D(0.5, 0.02, nm, transform=ax.transAxes, color=INK, fontsize=12,
                  family="monospace", weight="bold", ha="center")
    fig.suptitle("PitDivers rover — printable parts", color=INK, fontsize=15,
                 family="monospace", weight="bold", y=0.97)
    fig.savefig(os.path.join(OUT, "05_printable_parts.png"), facecolor=BG,
                bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)
    print("wrote 05_printable_parts.png")


sheet()
print("done")
