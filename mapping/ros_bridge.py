"""Replay durable PitDivers scans as ROS LaserScan and attach map poses to records.

Run collect.py concurrently to keep the SQLite database fed from the rover.
RF2O and SLAM Toolbox consume /scan and provide odom/map transforms.
"""

from __future__ import annotations

import argparse
import math
import json
import time
import os
from pathlib import Path
from collections import deque
from urllib.request import urlopen

import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import OccupancyGrid
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
from tf2_ros import Buffer, StaticTransformBroadcaster, TransformException, TransformListener

from records import ScanStore
from atomic_snapshot import replace_with_retry


class RoverBridge(Node):
    def __init__(self, db_path: str, forward_index: int, clockwise: bool, rate: float,
                 output=None, after_id=0, boot_id=None, live_url=None,
                 resume_after_gap=False, live_file=None, recover_localization=False, quality_file=None):
        super().__init__("pitdivers_scan_bridge")
        self.store = ScanStore(db_path)
        self.forward_index = forward_index % 360
        self.clockwise = clockwise
        self.last_id = after_id
        self.boot_id = boot_id
        self.live_url = live_url.rstrip('/') if live_url else None
        self.live_file = Path(live_file) if live_file else None
        self.resume_after_gap = resume_after_gap
        self.recover_localization = recover_localization
        self.quality_file = Path(quality_file) if quality_file else None
        self.had_gap = False
        self.recovery_start_pose = None
        self.recovery_scan_id = None
        self.recovery_count = 0
        self.pose_jump = False
        self.pending = deque()
        self.output = Path(output) if output else None
        self.created = time.time()
        self.run_id = os.urandom(6).hex()
        self.cells, self.path, self.environment, self.points = [], [], [], []
        self.resolution = .05
        self.pose = [0., 0., 0.]
        self.environment_keys = set()
        self.records = {}
        self.last_record = None
        self.blocked = False
        self.map_sub = self.create_subscription(OccupancyGrid, '/map', self.receive_map,
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE))
        self.pub = self.create_publisher(LaserScan, "/scan", qos_profile_sensor_data)
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.static_tf = StaticTransformBroadcaster(self)
        self.publish_mount_tf()
        self.create_timer(1.0 / rate, self.tick)
        self.create_timer(1., self.write_snapshot)

    def receive_map(self, msg):
        self.resolution = r = msg.info.resolution
        origin = msg.info.origin
        q = origin.orientation
        yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
        co, si = math.cos(yaw), math.sin(yaw)
        self.cells = []
        for i, value in enumerate(msg.data):
            if value < 0:
                continue
            x, y = (i % msg.info.width + .5)*r, (i // msg.info.width + .5)*r
            self.cells.append([math.floor((origin.position.x+co*x-si*y)/r),
                               math.floor((origin.position.y+si*x+co*y)/r),
                               8 if value >= 65 else -8 if value <= 25 else 0])

    def write_snapshot(self):
        if not self.output:
            return
        self.output.parent.mkdir(parents=True, exist_ok=True)
        reason = ('Localization pose jumped after Wi-Fi recovery; stop and re-localize' if self.pose_jump else
                  'Scan gap or rover restart: stop and restart the ROS mapping session' if self.blocked else
                  'LiDAR gap occurred; mapping resumed but alignment needs a new-room reset' if self.had_gap else
                  'RF2O + SLAM Toolbox · environmental positions are estimates at capture time')
        tracking = 'uncertain' if self.blocked or self.had_gap else 'tracking' if self.cells else 'waiting'
        if self.quality_file:
            try:
                quality = json.loads(self.quality_file.read_text())
                ready = quality.get('ready') and time.time()-quality['at'] < 1.
                tracking = 'tracking' if ready and not self.blocked else 'uncertain'
                reason = quality.get('reason', 'Waiting for verified localization')
            except (OSError, ValueError, KeyError):
                tracking, reason = 'uncertain', 'Waiting for localization quality'
        data = dict(run_id=self.run_id, created=self.created, saved_at=time.time(),
                    method='rf2o_slam_toolbox', loop_closure=True, last_id=self.last_id,
                    source_seq=self.last_record['seq'] if self.last_record else None,
                    source_boot=self.last_record['boot_id'] if self.last_record else None,
                    map=dict(resolution=self.resolution, cells=self.cells, path=self.path,
                             environment=self.environment, pose=self.pose, points=self.points,
                             placed=len(self.path), rejected=0, fitness=None, rmse=None,
                             tracking=tracking, reason=reason))
        temp = self.output.with_suffix('.tmp')
        temp.write_text(json.dumps(data, allow_nan=False))
        if not replace_with_retry(temp, self.output):
            return
        target = self.output.with_suffix('.jsonl')
        temp = target.with_suffix('.tmp-records')
        temp.write_text(''.join(json.dumps(r, allow_nan=False)+'\n' for r in self.records.values()))
        replace_with_retry(temp, target)

    def publish_mount_tf(self):
        # Set these values to the measured LiDAR displacement from rover centre.
        tf = TransformStamped()
        tf.header.stamp = self.get_clock().now().to_msg()
        tf.header.frame_id = "base_link"
        tf.child_frame_id = "lidar_link"
        tf.transform.rotation.w = 1.0
        self.static_tf.sendTransform(tf)

    def tick(self):
        if self.blocked or self.pub.get_subscription_count() < 2:
            self.attach_poses()
            return
        if self.live_url or self.live_file:
            try:
                if self.live_file:
                    shared = json.loads(self.live_file.read_text())
                    if time.time() - shared['received_at'] > 1.0:
                        self.attach_poses()
                        return
                    record = shared['record']
                else:
                    with urlopen(self.live_url + '/api/lidar/revolution', timeout=.7) as response:
                        record = json.load(response)
                if self.boot_id is not None and record['boot_id'] != self.boot_id:
                    self.blocked = True
                    return
                if self.last_record and record['seq'] <= self.last_record['seq']:
                    self.attach_poses()
                    return
                item = self.store.insert_live(record), record
            except (OSError, ValueError, KeyError) as exc:
                self.get_logger().warning(f'Waiting for live LiDAR: {exc}')
                self.attach_poses()
                return
        else:
            item = self.store.next_scan(self.last_id, boot_id=self.boot_id)
        if item:
            scan_id, record = item
            if self.last_record and (record['boot_id'] != self.last_record['boot_id'] or
                    ((record['start_ms']-self.last_record['end_ms']) & 0xffffffff) > 3000):
                if self.resume_after_gap and record['boot_id'] == self.last_record['boot_id']:
                    self.had_gap = True
                    if self.recover_localization:
                        self.recovery_start_pose = tuple(self.pose)
                        self.recovery_scan_id = scan_id
                        self.recovery_count = 0
                else:
                    self.blocked = True
                    return
            self.last_record = record
            self.records[scan_id] = dict(record, map_pose=None, map_run=self.run_id)
            stamp = self.get_clock().now().to_msg()
            msg = LaserScan()
            msg.header.stamp = stamp
            msg.header.frame_id = "lidar_link"
            msg.angle_min = -math.pi
            msg.angle_increment = math.tau / 360
            msg.angle_max = math.pi - msg.angle_increment
            msg.scan_time = max(0.05, record["scan_time_ms"] / 1000)
            # Ranges are reordered and no per-beam timestamps are retained.
            msg.time_increment = 0.0
            msg.range_min = 0.05
            msg.range_max = 6.0
            raw = record["ranges_mm"]
            msg.ranges = []
            for i in range(360):
                angle_deg = i - 180
                raw_index = (self.forward_index + (-angle_deg if self.clockwise else angle_deg)) % 360
                metres = raw[raw_index] / 1000.0
                msg.ranges.append(metres if msg.range_min <= metres <= msg.range_max else math.inf)
            self.pub.publish(msg)
            self.points = [[v*math.cos(msg.angle_min+i*msg.angle_increment),
                            v*math.sin(msg.angle_min+i*msg.angle_increment)]
                           for i,v in enumerate(msg.ranges) if math.isfinite(v)]
            self.pending.append((scan_id, stamp))
            if len(self.pending) > 500:
                self.pending.popleft()  # raw scan remains durable; no invented pose
            self.last_id = scan_id
        self.attach_poses()

    def attach_poses(self):
        # Transform may arrive a little after the scan. Keep raw data if no pose exists.
        if self.quality_file:
            try:
                quality = json.loads(self.quality_file.read_text())
                ready = quality.get('ready') and 0 <= time.time()-quality['at'] < 1.
            except (OSError, ValueError, KeyError):
                ready = False
            if not ready:
                self.pending.clear()  # raw records remain; don't map uncertain poses
                return
        for _ in range(min(len(self.pending), 20)):
            scan_id, stamp = self.pending.popleft()
            try:
                tf = self.tf_buffer.lookup_transform("map", "base_link", Time.from_msg(stamp))
            except TransformException:
                self.pending.append((scan_id, stamp))
                continue
            q = tf.transform.rotation
            yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
            p = tf.transform.translation
            self.store.set_pose(scan_id, p.x, p.y, yaw)
            self.records[scan_id]['map_pose'] = dict(x_m=p.x, y_m=p.y, yaw_rad=yaw)
            self.path.append([p.x, p.y, yaw, scan_id])
            self.path.sort(key=lambda p:p[3])
            self.pose = self.path[-1][:3]
            if self.recover_localization and self.had_gap and scan_id >= self.recovery_scan_id:
                if math.dist(self.pose[:2], self.recovery_start_pose[:2]) > .35:
                    self.pose_jump = self.blocked = True
                else:
                    self.recovery_count += 1
                    if self.recovery_count >= 15:
                        self.had_gap = False
                        self.recovery_start_pose = None
                        self.recovery_scan_id = None
            record = self.records[scan_id]
            age = record.get('environment_age_ms')
            key = (record['boot_id'], (record['end_ms']-age)&0xffffffff) if age is not None else None
            if age is not None and 0 <= age <= 3000 and key not in self.environment_keys:
                self.environment_keys.add(key)
                self.environment.append([p.x,p.y,record.get('temperature_c'),record.get('humidity_percent'),scan_id,age])

    def destroy_node(self):
        self.store.close()
        super().destroy_node()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="mapping/room_scans.sqlite3")
    parser.add_argument("--forward-index", type=int, default=0,
                        help="raw LiDAR degree aimed at rover front")
    parser.add_argument("--counterclockwise", action="store_true",
                        help="raw indices increase counterclockwise; default clockwise")
    parser.add_argument("--rate", type=float, default=5.0, help="replay scans per second")
    parser.add_argument('--output', help='Shared dashboard snapshot path')
    parser.add_argument('--after-id', type=int, default=0)
    parser.add_argument('--boot-id', type=int,
                        help='Only replay scans from the current rover boot; skip microSD backlog')
    parser.add_argument('--live-url', help='Use current rover revolutions for localization')
    parser.add_argument('--live-file', help='Read current rover revolutions from Windows dashboard relay')
    parser.add_argument('--resume-after-gap', action='store_true',
                        help='Continue mapping after a LiDAR gap, marking alignment uncertain')
    parser.add_argument('--recover-localization', action='store_true',
                        help='Recover a stationary saved-map pose after fresh, consistent scans')
    parser.add_argument('--quality-file', help='Require AMCL covariance and scan/map agreement')
    args = parser.parse_args()
    rclpy.init()
    node = RoverBridge(args.db, args.forward_index, not args.counterclockwise,
                       args.rate, args.output, args.after_id, args.boot_id,
                       args.live_url, args.resume_after_gap, args.live_file,
                       args.recover_localization, args.quality_file)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
