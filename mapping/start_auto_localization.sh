#!/usr/bin/env bash
# Automatically find position on the saved map. No motion on startup.
set -eo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="${1:-c3c666243fd2}"
[[ "$RUN" =~ ^[0-9a-f]{12}$ ]] || exit 2
test -s "$ROOT/data/ros-map/rebuilt-$RUN.json"
source /opt/ros/lyrical/setup.bash
source "$HOME/pitdivers_ros/install/setup.bash"
set -u
LOGDIR="$HOME/pitdivers_ros/logs/auto-$RUN"
mkdir -p "$LOGDIR"
SESSION="$ROOT/data/ros-map/localization-session.json"
QUALITY="$ROOT/data/ros-map/localization-quality.json"
pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
  sleep 1
  for pid in "${pids[@]}"; do kill -KILL "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -f "$SESSION"
}
trap cleanup EXIT
printf '{"at":%s,"mode":"amcl"}\n' "$(date +%s)" > "$SESSION"
# Mark the whole startup as a live session so archive downloads cannot block it.
(while true; do printf '{"at":%s,"mode":"amcl"}\n' "$(date +%s)" > "$SESSION"; sleep 1; done) & pids+=("$!")
BOOT_ID="$(python3 - "$ROOT/data/ros-map/latest-rover.json" <<'PY'
import json, sys, time
for _ in range(100):
    try:
        value=json.load(open(sys.argv[1]))
        if time.time()-value['received_at'] < 1:
            print(value['record']['boot_id']); break
    except (OSError, ValueError, KeyError): pass
    time.sleep(.1)
else: raise SystemExit('No fresh scan relay: start dashboard and LiDAR')
PY
)"
ros2 launch rf2o_laser_odometry rf2o_laser_odometry.launch.py >"$LOGDIR/rf2o.log" 2>&1 & pids+=("$!")
python3 "$ROOT/mapping/auto_localization.py" \
  --graph "$ROOT/data/ros-map/rebuilt-$RUN.json" --output "$QUALITY" \
  >"$LOGDIR/quality.log" 2>&1 & pids+=("$!")
ros2 run nav2_amcl amcl --ros-args --params-file "$ROOT/mapping/amcl.yaml" \
  >"$LOGDIR/amcl.log" 2>&1 & pids+=("$!")
sleep 3
ros2 lifecycle set /amcl configure
ros2 lifecycle set /amcl activate
python3 "$ROOT/mapping/ros_bridge.py" --db "$HOME/pitdivers_ros/room_scans.sqlite3" \
  --boot-id "$BOOT_ID" --live-file "$ROOT/data/ros-map/latest-rover.json" \
  --resume-after-gap --quality-file "$QUALITY" \
  --output "$ROOT/data/ros-map/localization-live.json" >"$LOGDIR/bridge.log" 2>&1 & pids+=("$!")
sleep 2
ros2 service call /pitdivers/relocalize std_srvs/srv/Empty '{}'
if [[ "${PITDIVERS_LOCALIZATION_ONLY:-0}" != "1" ]]; then
  python3 "$ROOT/mapping/autonav_ros.py" --map-id "$RUN" \
    --rover "${PITDIVERS_ROVER_URL:-http://192.168.0.99}" \
    >"$LOGDIR/autonav.log" 2>&1 & pids+=("$!")
fi
echo "Automatic localization on $RUN; motion stays idle until Go to B. Logs: $LOGDIR"
while true; do
  for pid in "${pids[@]}"; do kill -0 "$pid" 2>/dev/null || exit 1; done
  sleep 1
done
