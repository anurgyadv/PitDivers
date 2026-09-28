#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source /opt/ros/lyrical/setup.bash
source "$HOME/pitdivers_ros/install/setup.bash"
exec python3 "$ROOT/mapping/ros_stack.py"
