"""Guard wheel navigation against ROS replaying older stored LiDAR scans."""


def check_scan_lag(bridge_seq: int, database_seq: int,
                   live_seq: int | None, bridge_boot: int,
                   live_boot: int | None, max_lag: int = 10) -> str | None:
    if live_boot is not None and live_boot != bridge_boot:
        return 'LiDAR boot changed; restart localization'
    if bridge_seq > database_seq or database_seq - bridge_seq > max_lag:
        return 'ROS is replaying old LiDAR scans; restart localization at the live scan'
    if live_seq is not None and (live_seq < database_seq or live_seq - database_seq > max_lag):
        return 'LiDAR collector is behind the live rover'
    return None
