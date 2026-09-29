from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from webapp.missions import (
    MapObstacle,
    MapStore,
    Point,
    RouteWaypoint,
    RoverMap,
    WaypointAction,
    compile_plan,
    validate_map,
)


def valid_map() -> RoverMap:
    return RoverMap(
        name="Pump inspection",
        width_m=10,
        height_m=8,
        boundary=[
            Point(x=0.5, y=0.5),
            Point(x=9.5, y=0.5),
            Point(x=9.5, y=7.5),
            Point(x=0.5, y=7.5),
        ],
        obstacles=[
            MapObstacle(
                id="obs-1",
                name="Pump",
                polygon=[
                    Point(x=4, y=3),
                    Point(x=5, y=3),
                    Point(x=5, y=4),
                    Point(x=4, y=4),
                ],
            )
        ],
        route=[
            RouteWaypoint(id="wp-1", x=1, y=1, name="Home"),
            RouteWaypoint(
                id="wp-2",
                x=3,
                y=2,
                actions=[WaypointAction(type="take_photo", duration_s=1)],
            ),
            RouteWaypoint(id="wp-3", x=6, y=2),
        ],
    )


class MissionValidationTests(unittest.TestCase):
    def test_valid_route_compiles_to_motion_and_action_commands(self) -> None:
        rover_map = valid_map()
        report = validate_map(rover_map)
        plan = compile_plan(rover_map)

        self.assertTrue(report["valid"])
        self.assertAlmostEqual(report["metrics"]["route_length_m"], 5.236, places=3)
        self.assertEqual([item["command"] for item in plan["commands"]], [
            "MOVE_TO", "MOVE_TO", "TAKE_PHOTO", "MOVE_TO"
        ])

    def test_route_crossing_obstacle_is_rejected(self) -> None:
        rover_map = valid_map()
        rover_map.route = [
            RouteWaypoint(id="a", x=2, y=3.5),
            RouteWaypoint(id="b", x=7, y=3.5),
        ]

        report = validate_map(rover_map)

        self.assertFalse(report["valid"])
        self.assertTrue(any("crosses obstacle" in item for item in report["errors"]))

    def test_waypoint_outside_boundary_is_rejected(self) -> None:
        rover_map = valid_map()
        rover_map.route[-1].x = 9.8

        report = validate_map(rover_map)

        self.assertFalse(report["valid"])
        self.assertTrue(any("outside the operating boundary" in item for item in report["errors"]))


class MapStoreTests(unittest.TestCase):
    def test_round_trip_and_unique_names(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = MapStore(Path(folder))
            first = store.save(valid_map())
            second = store.save(valid_map())

            self.assertEqual(first.id, "pump-inspection")
            self.assertEqual(second.id, "pump-inspection-2")
            self.assertEqual(store.get(first.id).name, "Pump inspection")
            self.assertEqual(len(store.list()), 2)


if __name__ == "__main__":
    unittest.main()
