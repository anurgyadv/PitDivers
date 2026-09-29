# PitDivers expedition demo

This demo uses the laptop to control and record the rover on local Wi-Fi. A PC
on a different network runs DA3 and receives selected camera frames over
Tailscale. The laptop keeps the LiDAR map, sensor data, HTML report and returned
GLB.

## 1. Prepare the DA3 PC

Sign the PC and laptop in to the same tailnet. On the PC, open PowerShell in
the PitDivers repository and run:

```powershell
$env:PITDIVERS_REMOTE_TOKEN = '<one-long-random-token>'
.\vision\.venv\Scripts\python.exe -m webapp --no-browser
```

In another PC terminal, run `tailscale serve 8765`. Use `tailscale serve status`
to read the PC's private HTTPS `https://...ts.net` address. Leave both processes
running. The PC needs the DA3 checkpoint and a CUDA GPU. The token is a shared
transfer secret; use the same value in the laptop's Setup page.

## 2. Prepare the field laptop and rover

Connect the laptop to the rover's Wi-Fi. Start the laptop dashboard from the
PitDivers repository with `.\run_dashboard.ps1`, then open its dashboard URL.

On **Setup**, expand each device section:

1. **Camera ESP:** enter the actual JPEG stream URL (previously
   `http://192.168.0.119/jpg`).
2. **Wheel controller ESP:** enter `http://192.168.0.99`.
3. **Sensor ESP:** enter `http://192.168.0.99`. This firmware exposes
   `/api/environment` and `/api/imu` there. The fields remain separate in case
   sensors move to another ESP later.
4. **DA3 PC over Tailscale:** enter the PC's HTTPS `.ts.net` URL and the shared
   token, then select **Connect DA3 PC**. The laptop keeps these values only for
   the running dashboard session.

If Live shows **Reconnecting camera** after changing the camera URL, select
**Disconnect** on Live, then return to Expedition. Start will connect using the
new address.

Before driving, confirm that the camera stream works and the wheel ESP runs
the updated firmware with signed `POST /api/wheels` commands. The observed
`192.168.0.99` wheel-test firmware currently lacks that endpoint. The dashboard
uses signed commands because the old direction commands did not match physical
motion. Do the first directional check with wheels lifted and a person at the
stop control. A stationary recording demo can proceed without driving.

## 3. Run the expedition

On **Expedition**, enter the area or asset name and operator notes. Enter an
OpenRouter API key and choose an image-capable model. The key is used for this
report request and is not stored in the report.

Select **Start expedition**. The laptop connects the camera and wheel ESP,
starts LiDAR, and records a video, JPEG keyframes and ambient/IMU readings.
The camera and mini LiDAR map sit side by side. Select the mini map to open the
full live mapping view. Manual buttons drive only while held; release to stop.
The emergency stop is always visible. No gamepad is needed on this page.

Let the camera record at least two keyframes. Select **Stop & build report**.
The dashboard stops motion, ends recording, saves the LiDAR room, and creates
the interactive HTML report. It also packages up to 120 evenly spaced JPEG
frames and sends them privately to the DA3 PC. DA3 reconstructs `scene.glb`.
The laptop checks the job and, when complete, copies that GLB into the same
report folder and updates the existing HTML report. Reopen the report link to
see the interactive model.

## 4. Review and retain the evidence

Open the report from **Expedition** or **Reports**. Switch LiDAR, temperature
and humidity SVG layers; inspect the full photo timeline, recorded video,
sensor chart, AI observations and 3D model. Add human review notes. The report
and its companion assets are under `data/reports/<report-id>/`; keep that folder
together when copying it. The original capture is under `data/<capture-name>/`.

If the PC is offline, the report still contains available camera, LiDAR and
sensor evidence. After restoring Tailscale, use **Reports → Send capture to DA3
PC**, then **Check DA3**; this adds the completed GLB to reports for that capture.
If the camera is offline, correct its Setup URL before starting. The last
read-only check of `192.168.0.119/jpg` timed out on this laptop.
