# Live object detection

This starter reads the Freenove FNK0082 ESP32-S3 MJPEG camera stream on the
laptop and runs `PekingU/rtdetr_r18vd` through Hugging Face Transformers. The
ESP32 only captures and streams frames; the RTX 5070 performs inference.

The pretrained checkpoint detects the 80 general COCO categories, including
people, cars, trucks, backpacks, bottles, and chairs. Mine-specific findings
such as cracks, spills, loose rock, or damaged equipment will require a
labelled dataset and fine-tuning later.

## 1. Install Python and dependencies

Install 64-bit Python 3.11, then open PowerShell in the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
python -m pip install -r .\vision\requirements.txt
```

Confirm that PyTorch sees the RTX 5070:

```powershell
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

## 2. Find the camera stream URL

Read the ESP32 IP address from Arduino Serial Monitor. Open the camera page in
a browser and start its stream. The usual Espressif/Freenove MJPEG endpoint is:

```text
http://<ESP32-IP>:81/stream
```

If that does not open directly, inspect the stream link on the working camera
page and use its URL instead.

## 3. Run detection

```powershell
python .\vision\live_object_detection.py --stream-url http://<ESP32-IP>:81/stream
```

Press `Q` in the video window to stop. The first run downloads and caches the
public model weights (about 81 MB). A Hugging Face account or token is not
required for this public checkpoint.

Useful options:

```powershell
# Show only rover-relevant general classes
python .\vision\live_object_detection.py --stream-url http://<ESP32-IP>:81/stream --classes person car truck

# Lower the confidence threshold
python .\vision\live_object_detection.py --stream-url http://<ESP32-IP>:81/stream --threshold 0.40

# Try mixed precision after the standard run works
python .\vision\live_object_detection.py --stream-url http://<ESP32-IP>:81/stream --half
```

## Troubleshooting

- Camera page works but Python cannot open it: use the actual MJPEG stream URL,
  not the HTML control-page URL.
- Large delay: keep the ESP32 at QVGA initially and close other stream viewers.
- No boxes: test first with a person, chair, bottle, car, or another COCO class,
  and lower the threshold to `0.40`.
- CPU appears in the overlay: reinstall the CUDA-enabled PyTorch build and run
  the GPU verification command above.

## Live Depth Anything 3

DA3 can process the newest ESP32 frame continuously while a background capture
thread discards old buffered frames. The command below also saves two
keyframes per second for a final multi-view reconstruction:

```powershell
python .\vision\live_da3_depth.py `
  --stream-url http://<ESP32-IP>:81/stream `
  --process-res 392 `
  --inference-fps 5 `
  --keyframe-dir .\data\live_capture_01 `
  --keyframe-fps 2
```

This is live monocular depth, not a continuously fused global 3D map. After
the capture, process the saved keyframes into a spatially consistent GLB:

```powershell
da3 images .\data\live_capture_01 `
  --model-dir depth-anything/DA3-BASE `
  --export-format glb `
  --export-dir .\runs\live_capture_01
```

### Experimental expanding 3D map

The incremental mapper runs DA3 on overlapping windows and appends aligned
points to a native Open3D window while the rover moves:

```powershell
python .\vision\live_da3_map.py `
  --stream-url http://<ESP32-IP>:81/stream `
  --keyframe-dir .\data\live_map_01 `
  --output .\runs\live_map_01\map.ply
```

The first map appears after eight keyframes and updates every three new
keyframes. This online result is approximate, non-metric, and can drift. Move
slowly with sideways parallax and use the post-run full-batch GLB as the final
inspection artifact.
