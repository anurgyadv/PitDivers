# Rover Controller APK — Retroid Pocket Setup

## What this does

Native Android app that:
- Shows the camera board's live feed
- Shows the Windows room map in a bottom-left LiDAR minimap
- Falls back to the rover's latest 360° scan when the Windows map is unavailable
- Starts and stops the LiDAR from the Retroid
- Reads the Retroid's physical gamepad events and sends one ordered update every 75ms
- Sends tank-drive commands directly to the rover's HTTP API (no browser lag)
- Starts directly in Controller mode for the Retroid's built-in gamepad
- Uses B as an emergency stop and returns to Human mode when the app closes

## Default addresses

The APK starts with:

- Camera: `http://192.168.0.119/`
- Windows LiDAR dashboard: `http://192.168.0.57:8767`
- LiDAR rover: `http://192.168.0.99`
- Motion controller: `192.168.0.118`, API key `RANDOMKEY`

Use the **⚙ settings** button in the minimap to enter a different camera page
or stream link, Windows dashboard address, or LiDAR rover address. These three
URLs are saved on the Retroid. The motion-controller address remains in
`MainActivity.kt` because it uses the separate authenticated controller API.

Find these on your network:
- `rover_motion_control.ino` → open its Serial Monitor, look for `http://<IP>`
- `camera_dashboard.ino` → open its Serial Monitor, look for `http://<IP>`

## Building with Android Studio

1. Install Android Studio (Hedgehog or newer)
2. File → Open → select the `rover-controller/` folder
3. Wait for Gradle sync
4. Connect your Retroid via USB
5. Tools → Android → Device Manager → Select your Retroid → Play button
6. Or: Build APK (Build → Generate Signed Bundle / APK) and sideload it

## Using it

1. Open the app on your Retroid
2. Use the left stick to drive and steer
3. Hold **B** for emergency stop
4. The camera board page loads automatically
5. Tap the bottom-left LiDAR minimap to expand it
6. Tap **×** to return it to the bottom-left
7. Use **START/STOP** to turn the LiDAR on or off

The map label shows **PC MAP** while the accumulated Windows map is available.
After three PC connection failures it changes to **ROVER SCAN** and displays the
latest direct 360° scan. It switches back automatically when the PC returns.

For the accumulated map, launch `mapping/dashboard.py` with `--host 0.0.0.0`
and allow the selected port through Windows Firewall on private networks. The
normal PC browser can still open `http://127.0.0.1:8767/`.

## How the gamepad works

The app stores the latest physical gamepad event and transmits it through one
ordered HTTP worker every 75ms. It reads:
- **Left stick Y-axis** → forward/backward throttle
- **Left stick X-axis** → steering
- **B button** → emergency stop

This is the same mixing algorithm as `rover_gamepad_bridge.ps1`. A single
persistent worker prevents overlapping or out-of-order requests and keeps the
rover's 350ms controller lease refreshed.

## Troubleshooting

| Problem | Fix |
|---|---|
| Black camera screen | Open ⚙ and check the saved camera URL matches the camera board |
| Minimap stays on ROVER SCAN | Check the saved Windows dashboard URL and firewall |
| LiDAR command failed | Check the LiDAR rover URL and that `192.168.0.99` is reachable |
| Rover doesn't respond to sticks | Check `ROVER_IP` and `API_KEY` match the motion board |
| App crashes on startup | Ensure both boards are on the same WiFi as the Retroid |
| Sticks feel laggy | Check WiFi signal on all three devices |

## Notes

- The camera page is displayed in a WebView; physical gamepad input bypasses it
- Map polling and LiDAR commands use workers separate from motor control
- The gamepad input bypasses the WebView entirely — it goes straight to HTTP POSTs, just like the PowerShell bridge
- The rover's lease system (350ms for controller mode) handles dropped connections automatically
- No root or special permissions needed — just WiFi
