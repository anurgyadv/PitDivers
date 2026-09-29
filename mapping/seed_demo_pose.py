"""Initialize AMCL from the just-finished scan; quality checks still gate travel."""
import json,math,sys,time
import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
rclpy.init();node=rclpy.create_node('pitdivers_demo_initial_pose')
pub=node.create_publisher(PoseWithCovarianceStamped,'/initialpose',10)
deadline=time.monotonic()+5
while pub.get_subscription_count()==0 and time.monotonic()<deadline:
    rclpy.spin_once(node,timeout_sec=.1)
if pub.get_subscription_count()==0:raise RuntimeError('AMCL initial pose subscriber unavailable')
pose=json.load(open(sys.argv[1]))['map']['pose']
msg=PoseWithCovarianceStamped();msg.header.frame_id='map';msg.header.stamp=node.get_clock().now().to_msg()
msg.pose.pose.position.x=float(pose[0]);msg.pose.pose.position.y=float(pose[1])
msg.pose.pose.orientation.z=math.sin(pose[2]/2);msg.pose.pose.orientation.w=math.cos(pose[2]/2)
msg.pose.covariance[0]=msg.pose.covariance[7]=.15**2;msg.pose.covariance[35]=.20**2
pub.publish(msg)
for _ in range(5):rclpy.spin_once(node,timeout_sec=.1)
node.destroy_node();rclpy.shutdown()
