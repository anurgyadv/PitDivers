"""Supervised hallway out-and-back controller using ROS localization and LiDAR.

Started alongside start_saved_localization.sh. It stays idle until the local
dashboard writes a fresh command. All physical commands retain the ESP lease.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup, MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy, ReliabilityPolicy
from rclpy.time import Time
from nav_msgs.msg import OccupancyGrid
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformException, TransformListener

from autonav_core import Grid, MotionInputs, estimate_forward_offset, motion_command, turn_command, RecoveryGate, TurnProgress
from autonav_core import DRIVE_DUTY, TURN_DUTY, ARRIVAL_TOLERANCE_M, TURN_ENTRY_RAD, RECOVERY_STABLE_S
from demo_planner import plan_tour
from atomic_snapshot import replace_with_retry
from routes import RouteStore
from scan_lag import check_scan_lag
from live_costmap import LiveCostmap
from onboard_motion import OnboardClient
from drive_profile import predict_yaw, drive_duty, route_target

ROOT = Path(__file__).resolve().parent.parent
MISSION = ROOT / 'data/autonav'


class HallwayNavigator(Node):
    def __init__(self, rover: str, run_id: str, clearance_m: float):
        super().__init__('pitdivers_hallway_navigator')
        self.rover = rover.rstrip('/')
        self.run_id = run_id
        self.clearance_m = clearance_m
        self.routes = RouteStore(ROOT/'data/lidar-maps', ROOT/'data/lidar-routes')
        self.scan_db = Path.home()/'pitdivers_ros'/'room_scans.sqlite3'
        self.bridge_snapshot = ROOT/'data/ros-map'/'localization-live.json'
        self.quality_file = ROOT/'data/ros-map'/'localization-quality.json'
        graph = json.loads((ROOT/'data/ros-map'/f'rebuilt-{run_id}.json').read_text())
        self.graph_start = graph['map']['path'][0]
        self.grid = Grid.from_cells(graph['map']['cells'], graph['map']['resolution'])
        self.costmap = LiveCostmap(self.grid)
        self.current_scan = None
        self.forward_offset = (float(graph['forward_offset_rad']) if 'forward_offset_rad' in graph
                               else estimate_forward_offset(graph['map']['path']))
        self.remaining_goals = []
        self.demo_tour = False
        self.visited = 0
        self.total_stops = 0
        MISSION.mkdir(parents=True, exist_ok=True)
        self.command_file = MISSION/'command.json'
        self.status_file = MISSION/'status.json'
        self.seen = self.command_file.read_text() if self.command_file.exists() else ''
        self.state, self.reason = 'idle', 'Waiting for explicit Go to B'
        self.path = []
        self.goal = None
        self.remaining_goals = []
        self.round_trip = False
        self.return_start = None
        self.reverse = False
        self.pause_until = 0.0
        self.last_scan = 0.0
        self.nearest_front = 0.0
        self.nearest_rear = 0.0
        self.sweep_clearance = 0.0
        self.local_motion = None
        self.gyro_bias = None
        self.onboard_turn = False
        self.onboard_poll_at = 0.
        self.turn_completed_at = 0.
        self.turn_started = None
        self.turn_progress = None
        self.turn_diagnostics = None
        self.progress_pose = None
        self.progress_at = 0.
        self.recovery = None
        self.map_seen = False
        self.last_status = 0.0
        self.last_tick = time.monotonic()
        self.last_wheel_command = 0.0
        self.control_lock = threading.Lock()
        group = ReentrantCallbackGroup()
        self.create_subscription(LaserScan, '/scan', self.on_scan,
                                 qos_profile_sensor_data, callback_group=group)
        self.create_subscription(OccupancyGrid, '/map', self.on_map,
                                 QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                                            reliability=ReliabilityPolicy.RELIABLE), callback_group=group)
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.create_timer(.1, self.tick, callback_group=MutuallyExclusiveCallbackGroup())
        self.write_status()

    def on_map(self, msg):
        self.map_seen = bool(msg.data)

    def on_scan(self, msg):
        self.current_scan = msg
        def sector(bearing):
            return [distance for index, distance in enumerate(msg.ranges)
                    if abs(math.atan2(math.sin(msg.angle_min + index * msg.angle_increment - bearing),
                                      math.cos(msg.angle_min + index * msg.angle_increment - bearing)))
                       <= math.radians(20)
                    and math.isfinite(distance) and distance >= msg.range_min]
        front = sector(self.forward_offset)
        rear = sector(self.forward_offset + math.pi)
        self.nearest_front = min(front) if front else 0.0
        self.nearest_rear = min(rear) if rear else 0.0
        valid = [v for v in msg.ranges if math.isfinite(v) and .08 <= v < msg.range_max]
        self.sweep_clearance = min(valid) if len(valid) >= 180 else 0.
        self.last_scan = time.monotonic()

    def pose(self, frame='map'):
        try:
            transform = self.tf_buffer.lookup_transform(frame, 'base_link', Time())
        except TransformException:
            return None, math.inf
        stamp = Time.from_msg(transform.header.stamp)
        age = max(0.0, (self.get_clock().now().nanoseconds - stamp.nanoseconds) / 1e9)
        p, q = transform.transform.translation, transform.transform.rotation
        yaw = math.atan2(2 * (q.w*q.z + q.x*q.y), 1 - 2 * (q.y*q.y + q.z*q.z))
        return (p.x, p.y, yaw), age

    def send_wheels(self, a: int, b: int):
        query = urlencode({'a': a, 'b': b})
        with urlopen(Request(self.rover + '/api/wheels?' + query, data=b'', method='POST'),
                     timeout=.4) as response:
            result = json.load(response)
        if result.get('a') != a or result.get('b') != b:
            raise OSError('Wheel controller did not confirm the command')

    def scan_pipeline_reason(self, check_live=False):
        quality = self.localization_quality()
        if not quality['ready']:
            return quality['reason']
        snapshot = json.loads(self.bridge_snapshot.read_text())
        if snapshot.get('map', {}).get('tracking') != 'tracking':
            return snapshot.get('map', {}).get('reason') or 'ROS localization is uncertain'
        bridge_id = snapshot['last_id']
        with sqlite3.connect(self.scan_db, timeout=.2) as db:
            bridge = db.execute('SELECT boot_id, seq FROM scans WHERE id=?',
                                (bridge_id,)).fetchone()
            database_seq = (db.execute('SELECT MAX(seq) FROM scans WHERE boot_id=?',
                                       (bridge[0],)).fetchone()[0] if bridge else None)
        if not bridge or database_seq is None:
            return 'ROS LiDAR source record is missing'
        live_seq = live_boot = None
        if check_live:
            shared = json.loads((ROOT/'data/ros-map/latest-rover.json').read_text())
            if not 0 <= time.time() - shared['received_at'] < .6:
                return 'Waiting for fresh live LiDAR relay'
            live = shared['record']
            live_seq, live_boot = live['seq'], live['boot_id']
        return check_scan_lag(bridge[1], database_seq, live_seq,
                              bridge[0], live_boot)

    def localization_quality(self):
        try:
            value = json.loads(self.quality_file.read_text())
            if 0 <= time.time()-value['at'] < 1.:
                return value
        except (OSError, ValueError, KeyError):
            pass
        return {'ready': False, 'reason': 'Waiting for verified automatic localization'}

    def update_costmap(self):
        if not self.localization_quality()['ready']:
            self.costmap.reset()
            self.grid = self.costmap.grid
            return
        scan = self.current_scan
        if scan is None or time.monotonic()-self.last_scan > .6:
            return
        try:
            tf = self.tf_buffer.lookup_transform('map','base_link',Time.from_msg(scan.header.stamp))
        except TransformException:
            return
        p,q = tf.transform.translation,tf.transform.rotation
        yaw = math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
        points = [(v*math.cos(scan.angle_min+i*scan.angle_increment),
                   v*math.sin(scan.angle_min+i*scan.angle_increment))
                  for i,v in enumerate(scan.ranges) if math.isfinite(v) and .08<=v<5.95]
        self.grid = self.costmap.update((p.x,p.y,yaw),points,
            (scan.header.stamp.sec,scan.header.stamp.nanosec))

    def stop(self, state: str, reason: str):
        self.onboard_turn = False
        self.turn_completed_at = 0.
        self.state, self.reason = state, reason
        self.path = []
        self.goal = None
        self.round_trip = False
        self.reverse = False
        self.pause_until = 0.0
        self.last_wheel_command = 0.0
        self.turn_started = None
        self.turn_progress = None
        self.recovery = None
        try:
            with urlopen(self.rover + '/stop', timeout=.4) as response:
                response.read()
        except OSError:
            pass  # ESP drive/turn leases and local sensor guards remain active.
        self.write_status()

    def pause(self, reason):
        self.onboard_turn = False
        self.turn_completed_at = 0.
        self.state, self.reason = 'paused', reason + '; stopped while recovering'
        self.turn_started = None
        self.turn_progress = None
        self.recovery = RecoveryGate(time.monotonic())
        try:
            with urlopen(self.rover+'/stop',timeout=.4) as response:
                response.read()
        except OSError:
            pass
        self.write_status()

    def recover(self, now):
        pose, age = self.pose()
        healthy = (pose is not None and age < .6 and now-self.last_scan < .6
                   and self.localization_quality()['ready'])
        decision = self.recovery.update(now, healthy)
        if decision == 'timeout':
            self.stop('aborted', 'Recovery timed out; press Go to B after the issue is resolved')
            return
        if decision == 'resume':
            try:
                reason = self.scan_pipeline_reason(check_live=True)
                if reason:
                    raise ValueError(reason)
                path = self.grid.plan_from_nearby(pose[:2], self.goal, self.clearance_m)
                self.path = self.grid.smooth(path,self.clearance_m)
            except (ValueError,OSError,KeyError) as exc:
                self.reason = 'Paused: ' + str(exc)
                self.recovery.good_since = None
            else:
                self.state, self.reason = 'active', 'Continuing from verified current position'
                self.last_tick = time.monotonic()
                self.progress_pose, self.progress_at = pose[:2],self.last_tick
                self.last_wheel_command = 0.
                self.recovery = None
        if now-self.last_status > .3:
            self.write_status()

    def start(self, command: dict):
        if self.state in ('active', 'paused'):
            self.stop('cancelled', 'Replaced by a new start request')
        if not 0 <= time.time()-float(command.get('at', 0)) < 5:
            raise ValueError('Start request expired; press Go to B again')
        if command.get('map_id') != self.run_id:
            raise ValueError('Selected map differs from the loaded localization graph')
        if not isinstance(command.get('round_trip', False), bool):
            raise ValueError('Invalid round-trip option')
        route = self.routes.get(self.run_id) if 'targets' not in command else None
        if 'targets' not in command and (not route or not route.get('localization_destination')):
            raise ValueError('Mark B on the saved map before starting')
        if not self.map_seen:
            raise ValueError('ROS occupancy map is not available')
        pose, pose_age = self.pose()
        scan_age = time.monotonic() - self.last_scan
        if pose is None or pose_age > .6 or scan_age > .6 or self.nearest_front < .45:
            raise ValueError('Fresh localization and clear LiDAR scan are required')
        if 'targets' not in command and command.get('round_trip') and self.nearest_rear < .45:
            raise ValueError('LiDAR rear sector must be clear for the return trip')
        lag_reason = self.scan_pipeline_reason(check_live=True)
        if lag_reason:
            raise ValueError(lag_reason)
        with urlopen(self.rover + '/api/capabilities', timeout=.4) as response:
            capabilities = json.load(response)
        if not capabilities.get('signed_wheels') or capabilities.get('lease_ms', 9999) > 600:
            raise ValueError('Flash the signed-wheel Freenove firmware first')
        self.local_motion = None
        self.onboard_turn = False
        self.turn_completed_at = 0.
        if capabilities.get('onboard_motion') == 1:
            self.local_motion = OnboardClient(self.rover,self.forward_offset)
            local_status=self.local_motion.status()
            if not local_status.get('ready') or local_status.get('calibrating'):
                raise ValueError('Use Calibrate turns on this surface before starting gyro navigation')
            calibration=self.local_motion.request('/api/turn-calibration')
            self.gyro_bias=calibration.get('bias_dps') if calibration.get('ready') else None
        self.demo_tour = 'targets' in command
        self.remaining_goals = []
        self.visited = 0
        if self.demo_tour:
            tour=plan_tour(self.grid,pose[:2],command['targets'],command.get('round_trip',True),self.clearance_m)
            goals=tour['goals']
            self.total_stops=len(command['targets'])
            goal=goals[0]
            self.remaining_goals=goals[1:]
        else:
            destination = route['localization_destination']
            goal = destination['x_m'], destination['y_m']
        self.path = self.grid.plan_from_nearby(pose[:2], goal, self.clearance_m)
        self.path = self.grid.smooth(self.path, self.clearance_m)
        self.goal = goal
        self.round_trip = command.get('round_trip', False) and not self.demo_tour
        self.return_start = tuple(pose[:2])
        self.reverse = False
        self.turn_started = None
        self.turn_progress = None
        self.turn_diagnostics = None
        self.progress_pose = pose[:2]
        self.progress_at = time.monotonic()
        self.state, self.reason = 'active', 'Following clear observed cells toward B'
        # HTTP checks and route planning run before the control loop begins.
        # Count the watchdog interval from the completed plan, not the prior idle tick.
        self.last_tick = time.monotonic()
        self.write_status()

    def begin_return(self, pose, now):
        with urlopen(self.rover + '/stop', timeout=.4) as response:
            response.read()
        goal = self.return_start
        self.path = self.grid.plan_from_nearby(pose[:2], goal, self.clearance_m)
        self.path = self.grid.smooth(self.path, self.clearance_m)
        self.goal = goal
        self.reverse = True
        self.pause_until = now + 2.0
        self.progress_pose, self.progress_at = pose[:2], self.pause_until
        self.reason = 'At B; pausing before reverse return to A'
        self.write_status(pose)

    def advance_stop(self, pose, now):
        with urlopen(self.rover+'/stop',timeout=.4) as response:response.read()
        self.visited += 1
        if not self.remaining_goals:
            self.stop('arrived','Tour complete; rover stopped')
            return
        self.goal=self.remaining_goals.pop(0)
        self.path=self.grid.smooth(self.grid.plan_from_nearby(pose[:2],self.goal,self.clearance_m),self.clearance_m)
        self.reverse=False
        self.turn_started=self.turn_progress=None
        self.pause_until=now+.5
        self.progress_pose,self.progress_at=pose[:2],self.pause_until
        self.reason='Next stop' if self.visited<self.total_stops else 'Returning to trip start'
        self.write_status(pose)

    def target(self, pose):
        return route_target(self.path,pose,self.grid,self.clearance_m)

    def steering_yaw(self, pose, age):
        try:
            relay=json.loads((ROOT/'data/ros-map/latest-rover.json').read_text())
            return predict_yaw(pose[2],age,relay['record'].get('imu'),
                               time.time()-relay['received_at'],self.gyro_bias)
        except (OSError,ValueError,KeyError):return pose[2]

    def tick(self):
        now = time.monotonic()
        if not self.onboard_turn:
            self.update_costmap()
        command = self.command_file.read_text() if self.command_file.exists() else ''
        if command and command != self.seen:
            self.seen = command
            try:
                request = json.loads(command)
                if request.get('action') == 'cancel':
                    self.stop('cancelled', 'Cancelled by operator')
                elif request.get('action') == 'start':
                    self.start(request)
                else:
                    self.stop('rejected', 'Unknown mission command')
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                self.stop('rejected', str(exc))
        # A start command may spend time on HTTP checks and path planning.
        # Use the current time for the first active control cycle.
        now = time.monotonic()
        if self.state == 'paused':
            self.recover(now)
            self.last_tick = time.monotonic()
            return
        if self.state != 'active':
            if now - self.last_status > .3:
                self.write_status()
            self.last_tick = now
            return
        if now - self.last_tick > (1.4 if self.onboard_turn else .55):
            self.pause('Control process paused too long')
            return
        self.last_tick = now
        if not self.control_lock.acquire(blocking=False):
            return
        try:
            if self.onboard_turn:
                # An accepted bounded turn uses local sensors. It does not wait for
                # a ROS scan match between pushes; verify global pose after it stops.
                if now-self.onboard_poll_at >= .3:
                    local=self.local_motion.poll_turn();self.onboard_poll_at=time.monotonic()
                    self.turn_diagnostics=local
                    self.reason=local.get('reason','ESP gyro turn')
                    if local['mode']=='done':
                        self.onboard_turn=False
                        self.turn_started=None
                        self.turn_progress=None
                        self.progress_at=time.monotonic()
                        self.turn_completed_at=self.progress_at
                        self.last_tick=self.progress_at
                        self.pause_until=self.progress_at+.1
                        self.reason='Turn complete; verifying current map position'
                    self.write_status()
                return
            pose, pose_age = self.pose()
            if pose is None:
                self.pause('Localization lost')
                return
            if self.turn_completed_at:
                elapsed=now-self.turn_completed_at
                if elapsed < .25 or pose_age >= elapsed-.05 or self.last_scan<=self.turn_completed_at:
                    if elapsed>1.5:self.pause('Waiting for localization measured after the turn')
                    elif now-self.last_status>.3:self.write_status(pose)
                    return
                self.turn_completed_at=0.
                self.progress_pose=pose[:2];self.progress_at=now
            if pose_age > .6 or now-self.last_scan > .6:
                self.pause('Localization or LiDAR scan became stale')
                return
            lag_reason = self.scan_pipeline_reason()
            if lag_reason:
                self.pause(lag_reason)
                return
            forward_yaw = self.steering_yaw(pose,pose_age) + self.forward_offset
            travel_yaw = forward_yaw + (math.pi if self.reverse else 0)
            if not self.grid.is_free(pose[0], pose[1], .18):
                self.pause('Replanning around changed local obstacles')
                return
            if now < self.pause_until:
                if now - self.last_status > .3:
                    self.write_status(pose)
                return
            if math.dist(pose[:2], self.goal) < ARRIVAL_TOLERANCE_M:
                if self.demo_tour:
                    self.advance_stop(pose,now)
                elif self.round_trip and not self.reverse:
                    self.begin_return(pose, now)
                else:
                    self.stop('arrived', 'Returned to starting position' if self.reverse else 'Reached B')
                return
            forward_pose = (pose[0], pose[1], forward_yaw)
            inputs = MotionInputs(pose=forward_pose, pose_age_s=pose_age,
                                  scan_age_s=now-self.last_scan,
                                  nearest_front_m=self.nearest_rear if self.reverse else self.nearest_front,
                                  wifi_ok=True)
            target = self.target(pose)
            heading = math.atan2(target[1]-pose[1], target[0]-pose[0])
            error = math.atan2(math.sin(heading-travel_yaw), math.cos(heading-travel_yaw))
            if abs(error) > (.20 if self.turn_started is not None else TURN_ENTRY_RAD):
                if self.local_motion is not None:
                    if self.sweep_clearance < .45:
                        self.pause('LiDAR clearance is insufficient for a turn');return
                    self.local_motion.turn(math.degrees(error))
                    self.onboard_turn=True;self.onboard_poll_at=0.
                    self.last_tick=time.monotonic()
                    self.reason='ESP is turning using its gyro'
                    self.write_status(pose)
                    return
                odom, odom_age = self.pose('odom')
                if odom is None or odom_age > .6:
                    self.pause('Turn odometry became stale')
                    return
                duty = turn_command(inputs, target, self.sweep_clearance, self.reverse)
                if self.turn_progress is not None:
                    failure = self.turn_progress.update(now, odom[2])
                    self.turn_diagnostics = dict(
                        elapsed_s=round(now-self.turn_progress.started, 2),
                        no_progress_s=round(now-self.turn_progress.progress_at, 2),
                        rotation_deg=round(math.degrees(self.turn_progress.rotation), 2),
                        heading_error_deg=round(math.degrees(error), 2),
                        odom_age_s=round(odom_age, 3), duty=list(duty))
                    if failure:
                        self.stop('aborted', failure)
                        return
                    # Near +/-pi, heading noise can flip the desired turn. Hold
                    # the original direction until it is within the same half-circle.
                    if abs(error) > math.pi/2:
                        if duty != (0, 0):
                            sign = -self.turn_progress.direction
                            duty = (TURN_DUTY*sign, TURN_DUTY*sign)
                    elif duty != (0, 0) and (-1 if duty[0] > 0 else 1) != self.turn_progress.direction:
                        self.pause('Turn target changed direction; replanning')
                        return
                self.reason = 'Turning to follow the planned route'
                self.progress_pose, self.progress_at = pose[:2], now
            else:
                self.turn_started = None
                self.turn_progress = None
                if not self.grid.is_free(pose[0]+.12*math.cos(travel_yaw),
                                          pose[1]+.12*math.sin(travel_yaw), .18):
                    self.pause('Replanning around changed local obstacles')
                    return
                if math.dist(pose[:2], self.progress_pose) > .025:
                    self.progress_pose, self.progress_at = pose[:2], now
                if now-self.progress_at > 2.:
                    self.stop('aborted', 'Wheels commanded but no localization progress')
                    return
                duty = motion_command(inputs, target, reverse=self.reverse)
                self.reason = 'Driving toward B' if not self.reverse else 'Returning to start'
            if duty == (0, 0):
                self.pause('LiDAR clearance is insufficient for the requested motion')
                return
            if now - self.last_wheel_command >= .2:
                if self.local_motion is not None:
                    clearance=self.nearest_rear if self.reverse else self.nearest_front
                    straight=self.grid.segment_free(pose[:2],
                        (pose[0]+.6*math.cos(travel_yaw),pose[1]+.6*math.sin(travel_yaw)),self.clearance_m)
                    speed=drive_duty(error,clearance,math.dist(pose[:2],self.goal),straight)
                    self.local_motion.hold(math.degrees(error),-speed if self.reverse else speed)
                else:
                    self.send_wheels(*duty)
                self.last_wheel_command = time.monotonic()
                if self.reason == 'Turning to follow the planned route' and self.turn_progress is None:
                    self.turn_started = self.last_wheel_command
                    self.turn_progress = TurnProgress(self.turn_started, odom[2],
                                                      -1 if duty[0] > 0 else 1)
            if now - self.last_status > .3:
                self.write_status(pose)
        except (OSError, ValueError) as exc:
            self.pause(f'Wheel command failed: {exc}')
        finally:
            self.control_lock.release()

    def write_status(self, pose=None):
        self.last_status = time.monotonic()
        if pose is None:
            pose, pose_age = self.pose()
        else:
            pose_age = 0.0
        status = dict(at=time.time(), state=self.state, reason=self.reason,
                      map_id=self.run_id, pose=pose, goal=self.goal,
                      path_points=len(self.path), forward_offset_rad=round(self.forward_offset, 3),
                      phase='return' if self.reverse else 'outbound' if self.state in ('active','paused') else None,
                      map_ready=self.map_seen,
                      front_m=round(self.nearest_front, 3),
                      rear_m=round(self.nearest_rear, 3),
                      pose_age_s=round(pose_age, 3) if math.isfinite(pose_age) else None,
                      scan_age_s=round(time.monotonic()-self.last_scan, 3) if self.last_scan else None)
        quality = self.localization_quality()
        status['localization'] = quality
        status['sweep_clearance_m'] = round(self.sweep_clearance, 3)
        status['turn'] = self.turn_diagnostics
        status['motion_backend'] = 'esp_gyro' if self.local_motion is not None else 'legacy_ros'
        status['onboard_turn'] = self.onboard_turn
        status['remaining_goals'] = self.remaining_goals
        status['visited'] = self.visited
        status['total_stops'] = self.total_stops
        status['heading_rad'] = pose[2]+self.forward_offset if pose else None
        status['drive_profile'] = dict(name='smooth_demo', drive_pwm=DRIVE_DUTY,
            straight_pwm=200, lookahead_m=.6, gyro_prediction_max_s=.2,
            arrival_tolerance_m=ARRIVAL_TOLERANCE_M,
            recovery_stable_s=RECOVERY_STABLE_S, turn_entry_rad=TURN_ENTRY_RAD)
        status['path'] = self.path
        if self.state == 'idle':
            status['reason'] = ('Localized at current position; ready for Go to B'
                                if quality['ready'] else quality['reason'])
        temp = self.status_file.with_suffix('.tmp')
        temp.write_text(json.dumps(status, allow_nan=False))
        replace_with_retry(temp, self.status_file)

    def destroy_node(self):
        self.stop('idle', 'Navigation process stopped')
        super().destroy_node()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rover', default='http://192.168.0.99')
    parser.add_argument('--map-id', default='c3c666243fd2')
    parser.add_argument('--clearance-m', type=float, default=.23)
    args = parser.parse_args()
    rclpy.init()
    node = HallwayNavigator(args.rover, args.map_id, args.clearance_m)
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        executor.shutdown()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
