"""Publish the saved map and independently verify AMCL against live scans.

No motor commands. A ready result requires covariance, scan agreement and
several consecutive fresh scans; merely receiving a TF is never sufficient.
"""
import argparse
import json
import math
from pathlib import Path
import time
from collections import deque

import rclpy
from rclpy.node import Node
from rclpy.time import Time
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, qos_profile_sensor_data
from nav_msgs.msg import OccupancyGrid
from geometry_msgs.msg import PoseWithCovarianceStamped
from sensor_msgs.msg import LaserScan
from std_srvs.srv import Empty
from tf2_ros import Buffer, TransformListener, TransformException

from atomic_snapshot import replace_with_retry
from localization_quality import MapMatcher, quality_reason, AlignmentHistory


class AutoLocalization(Node):
    def __init__(self, graph, output):
        super().__init__('pitdivers_auto_localization')
        self.output = Path(output)
        data = json.loads(Path(graph).read_text())['map']
        self.matcher = MapMatcher(data['cells'], data['resolution'])
        self.publisher = self.create_publisher(OccupancyGrid, '/map',
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                       reliability=ReliabilityPolicy.RELIABLE))
        grid, origin = self.matcher.occupancy()
        self.map = OccupancyGrid()
        self.map.header.frame_id = 'map'
        self.map.info.resolution = self.matcher.resolution
        self.map.info.width, self.map.info.height = grid.shape[1], grid.shape[0]
        self.map.info.origin.position.x, self.map.info.origin.position.y = origin
        self.map.info.origin.orientation.w = 1.
        self.map.data = grid.flatten().tolist()
        self.publish_map()
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.scan = None
        self.scans = deque(maxlen=5)
        self.scan_at = self.pose_at = 0.
        self.xy_std = self.yaw_std = math.inf
        self.count = 0
        self.alignment = AlignmentHistory()
        self.last_stamp = None
        self.last_map_odom = None
        self.stable_since = None
        self.status = {}
        self.nomotion = self.create_client(Empty, '/request_nomotion_update')
        self.global_client = self.create_client(Empty, '/reinitialize_global_localization')
        self.nomotion_future = None
        self.create_service(Empty, '/pitdivers/relocalize', self.relocalize)
        self.create_subscription(LaserScan, '/scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', self.on_pose, 10)
        self.create_timer(.2, self.tick)
        self.create_timer(.5, self.force_update)
        self.write(False, 'Searching the saved map', {}, None)

    def publish_map(self):
        self.map.header.stamp = self.get_clock().now().to_msg()
        self.publisher.publish(self.map)

    def on_scan(self, msg):
        self.scan, self.scan_at = msg, time.monotonic()
        self.scans.append((msg, self.scan_at))

    def on_pose(self, msg):
        cov = msg.pose.covariance
        self.xy_std = math.sqrt(max(0., cov[0], cov[7]))
        self.yaw_std = math.sqrt(max(0., cov[35]))
        self.pose_at = time.monotonic()

    def force_update(self):
        if (self.scan is not None and time.monotonic() - self.scan_at < .6
                and self.nomotion.service_is_ready()
                and (self.nomotion_future is None or self.nomotion_future.done())):
            self.nomotion_future = self.nomotion.call_async(Empty.Request())

    def relocalize(self, request, response):
        self.alignment.reset()
        self.count, self.stable_since = 0, None
        self.pose_at = 0.
        self.xy_std = self.yaw_std = math.inf
        self.write(False, 'Searching all positions and headings on the saved map', {}, None)
        if self.global_client.service_is_ready():
            self.global_client.call_async(Empty.Request())
        return response

    def tick(self):
        now = time.monotonic()
        pose, fit = None, {}
        reason = 'Waiting for live LiDAR and AMCL'
        selected_stamp = None
        transport_gap = False
        for scan, received_at in reversed(self.scans):
            try:
                tf = self.buffer.lookup_transform('map', 'base_link', Time.from_msg(scan.header.stamp))
                p, q = tf.transform.translation, tf.transform.rotation
                yaw = math.atan2(2*(q.w*q.z + q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
                pose = [p.x, p.y, yaw]
                points = [[r*math.cos(scan.angle_min+i*scan.angle_increment),
                           r*math.sin(scan.angle_min+i*scan.angle_increment)]
                          for i, r in enumerate(scan.ranges)
                          if math.isfinite(r) and .08 <= r < 5.95]
                fit = self.matcher.score(points, pose)
                reason = quality_reason(fit, self.xy_std, self.yaw_std,
                                        now-received_at, now-self.pose_at)
                transport_gap = (reason == 'Waiting for fresh LiDAR' and
                    quality_reason(fit,self.xy_std,self.yaw_std,0.,now-self.pose_at) is None)
                correction = self.buffer.lookup_transform('map','odom',Time.from_msg(scan.header.stamp))
                t,qc = correction.transform.translation,correction.transform.rotation
                cyaw = math.atan2(2*(qc.w*qc.z+qc.x*qc.y),1-2*(qc.y*qc.y+qc.z*qc.z))
                current = (t.x,t.y,cyaw)
                if self.last_map_odom:
                    old = self.last_map_odom
                    da = abs(math.atan2(math.sin(cyaw-old[2]),math.cos(cyaw-old[2])))
                    if math.dist(current[:2],old[:2]) > .25 or da > .20:
                        reason = 'Pose correction detected; confirming alignment before motion'
                        transport_gap = False
                self.last_map_odom = current
                selected_stamp = (scan.header.stamp.sec, scan.header.stamp.nanosec)
                break
            except TransformException:
                reason = 'Searching the saved map; waiting for pose transform'
        stamp = selected_stamp
        ready = self.alignment.update(now,stamp,reason,transport_gap)
        self.count,self.stable_since = self.alignment.count,self.alignment.since
        self.last_stamp = stamp
        self.write(ready, reason or ('Localized: scan matches the saved map' if ready
                                   else 'Confirming scan agreement across fresh scans'), fit, pose)

    def write(self, ready, reason, fit, pose):
        self.status = dict(at=time.time(), ready=bool(ready), reason=reason, pose=pose,
                           fit=fit, consistent_scans=self.count,
                           xy_std_m=self.xy_std if math.isfinite(self.xy_std) else None,
                           yaw_std_rad=self.yaw_std if math.isfinite(self.yaw_std) else None)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        temp = self.output.with_suffix('.tmp')
        temp.write_text(json.dumps(self.status, allow_nan=False))
        replace_with_retry(temp, self.output)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--graph', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    rclpy.init()
    node = AutoLocalization(args.graph, args.output)
    try:
        rclpy.spin(node)
    finally:
        node.write(False, 'Localization stopped', {}, None)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
