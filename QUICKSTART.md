# Quick start — run the dashboard on any device

Brief steps to get the PitDivers dashboard running. Works with or without an
NVIDIA GPU. The camera/sensor firmware is separate — see
[`firmware/.../README.md`](firmware/PitDivers_Camera_DHT11/README.md).

**Prerequisites:** Python 3.10–3.12 and Git. A CUDA GPU is optional (CPU works,
just slower).

### 1. Clone

```bash
git clone https://github.com/anurgyadv/PitDivers.git
cd PitDivers
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
```

### 3. Install PyTorch (pick one)

```bash
# CPU only (no NVIDIA GPU) — e.g. a Core i5 laptop:
pip install torch torchvision

# NVIDIA GPU (example: CUDA 12.8 build):
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

### 4. Install the dashboard dependencies

```bash
pip install -r requirements-app.txt
```

### 5. Run

```bash
python -m webapp
```

Then open **http://127.0.0.1:8765** (it also tries to open automatically).

### 6. Connect

Enter the ESP32 stream URL (e.g. `http://192.168.0.69:81/stream`), pick a model,
and press **Connect**. Depth appears once the model loads.

---

## No GPU? (CPU mode)

Live depth runs on CPU but is **seconds per frame**, not smooth. For a usable
preview:

- Model: **DA3 Small**
- Processing resolution: **lowest** (~280)
- Inference FPS: **1–2**
- Or press **Depth: Off** to run the camera only with no depth cost — you can
  still record keyframes and reconstruct on a GPU machine later.

**Offline 3D reconstruction (Build 3D) is GPU-oriented** — a full multi-view DA3
run on a CPU takes many minutes and can exhaust RAM. Do reconstruction on a
machine with an NVIDIA GPU.

## Windows one-click launcher (optional)

After steps 1–4, `Start PitDivers Dashboard.cmd` launches the dashboard. It
looks for the virtual environment at `vision\.venv`, so on Windows create the
venv there instead of `.venv` if you want the launcher to find it:

```powershell
python -m venv vision\.venv
.\vision\.venv\Scripts\Activate.ps1
```

## Troubleshooting

- **`ModuleNotFoundError` on connect / Build 3D** — reinstall step 4; the DA3
  code needs everything in `requirements-app.txt`, not just the web packages.
- **Overlay says "CPU mode"** — expected with no GPU; live depth still works.
- **`pycolmap` fails to install** — upgrade pip (`pip install -U pip`) so it can
  fetch the prebuilt wheel.
- **Meshing tool** (`tools/mesh_from_glb.py`) needs its own extras:
  `pip install -r tools/requirements.txt`.
