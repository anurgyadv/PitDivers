#!/usr/bin/env bash
# Rebuild a SLAM Toolbox pose graph from a saved PitDivers ROS map's raw scans.
# Run inside WSL after sourcing ROS and the local rf2o workspace.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAP="${1:-$ROOT/data/lidar-maps/c3c666243fd2.json}"
RUN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$MAP")"
read -r FIRST LAST < <(python3 -c 'import json,sys; p=json.load(open(sys.argv[1]))["map"]["path"]; print(p[0][3],p[-1][3])' "$MAP")
WORK="$HOME/pitdivers_ros"
DB="$WORK/room_scans.sqlite3"
OUT="$ROOT/data/ros-map/rebuilt-$RUN.json"
GRAPH="$ROOT/data/lidar-maps/$RUN-posegraph"
LOGDIR="$WORK/logs/rebuild-$RUN"
mkdir -p "$LOGDIR"

# Replaying into a copy keeps stored live-session poses intact.
COPY="$LOGDIR/scans.sqlite3"
python3 - "$DB" "$COPY" <<'PY'
import sqlite3, sys
source = sqlite3.connect(sys.argv[1])
target = sqlite3.connect(sys.argv[2])
source.backup(target)
target.close()
source.close()
PY

rf2o_pid=""; slam_pid=""; bridge_pid=""
cleanup() {
  for pid in "$bridge_pid" "$slam_pid" "$rf2o_pid"; do
    if [[ -n "$pid" ]]; then kill -TERM "$pid" 2>/dev/null || true; fi
  done
  for _ in {1..10}; do
    alive=0
    for pid in "$bridge_pid" "$slam_pid" "$rf2o_pid"; do
      if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then alive=1; fi
    done
    if (( ! alive )); then break; fi
    sleep 0.5
  done
  for pid in "$bridge_pid" "$slam_pid" "$rf2o_pid"; do
    if [[ -n "$pid" ]]; then kill -KILL "$pid" 2>/dev/null || true; fi
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT

ros2 launch rf2o_laser_odometry rf2o_laser_odometry.launch.py >"$LOGDIR/rf2o.log" 2>&1 & rf2o_pid=$!
ros2 launch slam_toolbox online_async_launch.py "slam_params_file:=$ROOT/mapping/slam.yaml" >"$LOGDIR/slam.log" 2>&1 & slam_pid=$!
sleep 6
python3 "$ROOT/mapping/ros_bridge.py" --db "$COPY" --output "$OUT" \
  --after-id "$((FIRST - 1))" --rate 5 >"$LOGDIR/bridge.log" 2>&1 & bridge_pid=$!

echo "Replaying scans $FIRST..$LAST from $RUN; this takes about 3 minutes."
deadline=$((SECONDS + 300))
while (( SECONDS < deadline )); do
  kill -0 "$bridge_pid" && kill -0 "$slam_pid" && kill -0 "$rf2o_pid" || {
    echo "A ROS process exited; inspect $LOGDIR" >&2; exit 1;
  }
  read -r CURRENT PLACED < <(python3 - "$OUT" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    print(data['last_id'], data['map']['placed'])
except (OSError, ValueError, KeyError):
    print(0, 0)
PY
  )
  if (( CURRENT >= LAST && PLACED >= LAST - FIRST - 10 )); then break; fi
  sleep 3
done
if (( CURRENT < LAST || PLACED < LAST - FIRST - 10 )); then
  echo "Replay incomplete: last scan $CURRENT/$LAST, posed $PLACED; inspect $LOGDIR" >&2
  exit 1
fi

sleep 8  # allow the final asynchronous SLAM updates to settle
ros2 service call /slam_toolbox/serialize_map slam_toolbox/srv/SerializePoseGraph \
  "{filename: '$GRAPH'}" | tee "$LOGDIR/serialize.log"
grep -q 'SerializePoseGraph_Response(result=0)' "$LOGDIR/serialize.log"
test -s "$GRAPH.posegraph"
test -s "$GRAPH.data"
echo "Saved localization graph: $GRAPH.posegraph and $GRAPH.data"
