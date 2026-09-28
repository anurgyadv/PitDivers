#!/usr/bin/env bash
# Run interactively in WSL as your regular Linux user. Uses official ROS packages.
set -eo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
. /etc/os-release
if [ "${VERSION_CODENAME}" != resolute ]; then
  echo 'This installer is for Ubuntu 26.04 (resolute).'
  exit 1
fi
sudo -v
export LANG=C.UTF-8
sudo apt-get update
sudo apt-get install -y curl ca-certificates git libeigen3-dev
ros_source_deb="$(mktemp --suffix=.deb)"
curl -fL https://github.com/ros-infrastructure/ros-apt-source/releases/download/1.3.0/ros2-apt-source_1.3.0.resolute_all.deb -o "$ros_source_deb"
sudo dpkg -i "$ros_source_deb"
sudo apt-get update
sudo apt-get install -y ros-lyrical-ros-base ros-lyrical-slam-toolbox ros-lyrical-rviz2 ros-dev-tools
source /opt/ros/lyrical/setup.bash
workspace="$HOME/pitdivers_ros"
mkdir -p "$workspace/src"
if [ ! -d "$workspace/src/rf2o_laser_odometry" ]; then
  git clone --branch ros2 --single-branch https://github.com/MAPIRlab/rf2o_laser_odometry.git "$workspace/src/rf2o_laser_odometry"
fi
python3 "$script_dir/patch_rf2o_lyrical.py" "$workspace/src/rf2o_laser_odometry"
if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then
  sudo rosdep init
fi
rosdep update
cd "$workspace"
rosdep install --from-paths src --ignore-src -y --rosdistro lyrical
colcon build --symlink-install --packages-select rf2o_laser_odometry --cmake-args -DCMAKE_BUILD_TYPE=Release
source "$workspace/install/setup.bash"
ros2 pkg prefix slam_toolbox
ros2 pkg prefix rf2o_laser_odometry
echo 'PitDivers ROS setup complete.'
