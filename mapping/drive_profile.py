"""Bounded steering prediction and clearance-aware straight-line speed."""
import math

def predict_yaw(yaw, age, imu, relay_age, bias):
    if bias is None or not 0 <= age <= .2 or not 0 <= relay_age <= .2:
        return yaw
    try:
        z=imu['gyro_dps'][2]; az=imu['accel_g'][2]
        if not all(math.isfinite(x) for x in (z,az,bias)) or abs(z)>=240 or not .85<=abs(az)<=1.15 or not 0<=imu['age_ms']<=100:
            return yaw
        return yaw+math.radians((z-bias)*(1 if az>0 else -1))*age
    except (KeyError,TypeError,IndexError):
        return yaw

def drive_duty(error, clearance, distance, straight_free):
    return 200 if abs(error)<math.radians(10) and clearance>=1.2 and distance>=.8 and straight_free else 180

def route_target(path, pose, grid, clearance):
    nearest=min(range(len(path)),key=lambda i:math.dist(pose[:2],path[i]))
    fallback=path[-1]
    for point in path[nearest:]:
        if math.dist(pose[:2],point)>=.25:
            fallback=point;break
    # Longer lookahead only through observed clear space; never cut a corner.
    for point in reversed(path[nearest:]):
        if math.dist(pose[:2],point)<=.6 and grid.segment_free(pose[:2],point,clearance):
            return point
    return fallback
