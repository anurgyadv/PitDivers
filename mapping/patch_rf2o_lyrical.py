"""Apply the upstream ROS 2 RF2O build's Lyrical compatibility changes.

Original files are retained alongside edits as .pitdivers-original backups.
Run inside WSL: python3 patch_rf2o_lyrical.py ~/pitdivers_ros/src/rf2o_laser_odometry
"""
from pathlib import Path
import re
import shutil
import sys

root = Path(sys.argv[1]).expanduser().resolve()


def update(path, text):
    original = path.with_name(path.name + '.pitdivers-original')
    if path.read_text() == text:
        return
    if not original.exists():
        shutil.copy2(path, original)
    path.write_text(text)
    print('Updated', path.name)


manifest = root / 'package.xml'
text = manifest.read_text()
text = re.sub(r'^.*<(?:build_depend|run_depend)>cmake_modules</(?:build_depend|run_depend)>.*\n', '', text, flags=re.M)
if '<build_depend>nav_msgs</build_depend>' not in text:
    text = text.replace('  <export>', '  <build_depend>nav_msgs</build_depend>\n  <run_depend>nav_msgs</run_depend>\n  <export>')
update(manifest, text)

cmake = '''cmake_minimum_required(VERSION 3.16)
project(rf2o_laser_odometry)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)
find_package(Eigen3 REQUIRED)

add_library(${PROJECT_NAME} src/CLaserOdometry2D.cpp)
add_executable(rf2o_laser_odometry_node src/CLaserOdometry2DNode.cpp)
foreach(target ${PROJECT_NAME} rf2o_laser_odometry_node)
  target_include_directories(${target} PUBLIC include)
  target_link_libraries(${target} PUBLIC
    rclcpp::rclcpp tf2::tf2 tf2_ros::tf2_ros
    tf2_geometry_msgs::tf2_geometry_msgs Eigen3::Eigen
    ${std_msgs_TARGETS} ${geometry_msgs_TARGETS} ${sensor_msgs_TARGETS} ${nav_msgs_TARGETS})
endforeach()
target_link_libraries(rf2o_laser_odometry_node PRIVATE ${PROJECT_NAME})
install(TARGETS ${PROJECT_NAME} ARCHIVE DESTINATION lib LIBRARY DESTINATION lib)
install(TARGETS rf2o_laser_odometry_node DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})
ament_package()
'''
update(root / 'CMakeLists.txt', cmake)

for path in (root / 'include').rglob('*.hpp'):
    text = path.read_text()
    text = re.sub(r'(#include <tf2(?:_ros)?/[^>]+)\.h>', r'\1.hpp>', text)
    update(path, text)
