"""Rutas manuales no oficiales que los vehículos pueden utilizar como desvíos temporales."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import List, Optional, Tuple

import pygame

from traffic_accidents import TemporaryDetour


Point = Tuple[float, float]


@dataclass(frozen=True)
class ManualExtraRoute:
    route_id: int
    axis: str
    road_index: int
    lane_index: int
    lane_direction: str
    lateral_position: float
    start: Point
    end: Point

    @property
    def center(self) -> Point:
        return ((self.start[0] + self.end[0]) / 2, (self.start[1] + self.end[1]) / 2)


class ManualExtraRouteSystem:
    """Stores user-placed unofficial routes drawn over roads or non-road areas."""

    LANE_SNAP_DISTANCE = 11

    def __init__(self, map_generator) -> None:
        self.map_generator = map_generator
        self.routes: List[ManualExtraRoute] = []
        self._next_id = 1
        self._font: Optional[pygame.font.Font] = None
        self.refresh()

    def __len__(self) -> int:
        return len(self.routes)

    def clear(self) -> None:
        self.routes.clear()

    def refresh(self) -> None:
        self._horizontal_roads = {}
        self._vertical_roads = {}
        self._lane_targets = []
        for inter in self.map_generator.get_intersections():
            self._horizontal_roads[inter.row] = inter.cy
            self._vertical_roads[inter.col] = inter.cx
        for spawn in self.map_generator.get_spawn_points():
            if spawn.direction in ("right", "left"):
                self._lane_targets.append(
                    {
                        "axis": "horizontal",
                        "road_index": spawn.lane // 2,
                        "lane_index": spawn.lane,
                        "direction": spawn.direction,
                        "lateral": spawn.spawn_y,
                    }
                )
            else:
                self._lane_targets.append(
                    {
                        "axis": "vertical",
                        "road_index": spawn.lane // 2,
                        "lane_index": spawn.lane,
                        "direction": spawn.direction,
                        "lateral": spawn.spawn_x,
                    }
                )

    def place_near(self, position: Point) -> ManualExtraRoute:
        """Add a route on a lane or next to a street, linked to the nearest road."""
        x, y = position
        lane = min(
            self._lane_targets,
            key=lambda item: (
                abs(y - item["lateral"])
                if item["axis"] == "horizontal"
                else abs(x - item["lateral"])
            ),
        )
        lane_distance = (
            abs(y - lane["lateral"])
            if lane["axis"] == "horizontal"
            else abs(x - lane["lateral"])
        )
        snap_to_lane = lane_distance <= self.LANE_SNAP_DISTANCE
        length = self.map_generator.road_width * 3.2
        if lane["axis"] == "horizontal":
            lateral = lane["lateral"] if snap_to_lane else y
            start = (max(0, x - length / 2), y)
            end = (min(self.map_generator.total_width, x + length / 2), y)
            route = ManualExtraRoute(
                self._next_id,
                "horizontal",
                lane["road_index"],
                lane["lane_index"],
                lane["direction"] if snap_to_lane else "costado",
                lateral,
                (start[0], lateral),
                (end[0], lateral),
            )
        else:
            lateral = lane["lateral"] if snap_to_lane else x
            start = (x, max(0, y - length / 2))
            end = (x, min(self.map_generator.total_height, y + length / 2))
            route = ManualExtraRoute(
                self._next_id,
                "vertical",
                lane["road_index"],
                lane["lane_index"],
                lane["direction"] if snap_to_lane else "costado",
                lateral,
                (lateral, start[1]),
                (lateral, end[1]),
            )

        self.routes.append(route)
        self._next_id += 1
        return route

    def detour_for(self, accident) -> Optional[TemporaryDetour]:
        candidates = [
            route
            for route in self.routes
            if self._route_spans_accident(route, accident)
        ]
        if not candidates:
            return None

        route = min(
            candidates,
            key=lambda item: (
                0 if item.axis == ("horizontal" if accident.direction in ("right", "left") else "vertical") else 1,
                abs(item.lateral_position - self._accident_lateral(accident)),
            ),
        )
        if route.axis == "horizontal" and accident.direction in ("right", "down"):
            clear_after = route.end[0]
        elif route.axis == "horizontal":
            clear_after = route.start[0]
        elif accident.direction in ("right", "down"):
            clear_after = route.end[1]
        else:
            clear_after = route.start[1]

        return TemporaryDetour(
            accident.intersection,
            accident.direction,
            accident.road_index,
            route.axis,
            route.lateral_position,
            clear_after,
            frozenset((accident.accident_id,)),
        )

    def reserved_lane_ahead(
        self, direction: str, lane_index: int, front_position: float
    ) -> Tuple[float, Optional[ManualExtraRoute]]:
        """Return the nearest manual route reserving this lane for a detour."""
        nearest_distance = float("inf")
        nearest_route = None
        for route in self.routes:
            if route.lane_direction != direction or route.lane_index != lane_index:
                continue

            distance = self._distance_ahead_to_route(route, direction, front_position)
            if distance is not None and distance < nearest_distance:
                nearest_distance = distance
                nearest_route = route

        return nearest_distance, nearest_route

    def remove_near(self, position: Point, radius: float = 28) -> bool:
        if not self.routes:
            return False
        route = min(self.routes, key=lambda item: self._distance_to_route(position, item))
        if self._distance_to_route(position, route) > radius:
            return False
        self.routes.remove(route)
        return True

    def draw(self, surface: pygame.Surface) -> None:
        if self._font is None:
            self._font = pygame.font.SysFont("arial", 11, bold=True)
        for route in self.routes:
            self._dashed_line(surface, (255, 150, 40), route.start, route.end, 4)
            label = self._font.render(f"RUTA EXTRA ({route.lane_direction})", True, (255, 226, 190))
            cx, cy = route.center
            surface.blit(label, (cx - label.get_width() / 2, cy + 8))

    def _route_spans_accident(self, route: ManualExtraRoute, accident) -> bool:
        margin = self.map_generator.road_width * 1.35
        if route.axis == "horizontal":
            left, right = sorted((route.start[0], route.end[0]))
            same_axis = accident.direction in ("right", "left")
            close_cross = abs(accident.position[1] - self._road_center_y(route.road_index)) <= margin
            spans = left - margin <= accident.position[0] <= right + margin
            return (same_axis and accident.road_index == route.road_index and spans) or (
                not same_axis
                and spans
                and close_cross
            )
        top, bottom = sorted((route.start[1], route.end[1]))
        same_axis = accident.direction in ("up", "down")
        close_cross = abs(accident.position[0] - self._road_center_x(route.road_index)) <= margin
        spans = top - margin <= accident.position[1] <= bottom + margin
        return (same_axis and accident.road_index == route.road_index and spans) or (
            not same_axis
            and spans
            and close_cross
        )

    @staticmethod
    def _distance_ahead_to_route(
        route: ManualExtraRoute, direction: str, front_position: float
    ) -> Optional[float]:
        if direction in ("right", "left"):
            left, right = sorted((route.start[0], route.end[0]))
            if direction == "right":
                if front_position > right:
                    return None
                return max(0.0, left - front_position)
            if front_position < left:
                return None
            return max(0.0, front_position - right)

        top, bottom = sorted((route.start[1], route.end[1]))
        if direction == "down":
            if front_position > bottom:
                return None
            return max(0.0, top - front_position)
        if front_position < top:
            return None
        return max(0.0, front_position - bottom)

    def _road_center_y(self, road_index: int) -> float:
        return self._horizontal_roads.get(road_index, 0)

    def _road_center_x(self, road_index: int) -> float:
        return self._vertical_roads.get(road_index, 0)

    @staticmethod
    def _accident_lateral(accident) -> float:
        if accident.direction in ("right", "left"):
            return accident.position[1]
        return accident.position[0]

    @staticmethod
    def _distance_to_route(position: Point, route: ManualExtraRoute) -> float:
        x, y = position
        if route.axis == "horizontal":
            left, right = sorted((route.start[0], route.end[0]))
            closest_x = max(left, min(right, x))
            return math.hypot(x - closest_x, y - route.lateral_position)
        top, bottom = sorted((route.start[1], route.end[1]))
        closest_y = max(top, min(bottom, y))
        return math.hypot(x - route.lateral_position, y - closest_y)

    @staticmethod
    def _dashed_line(
        surface: pygame.Surface,
        color: Tuple[int, int, int],
        start: Point,
        end: Point,
        width: int,
    ) -> None:
        length = math.dist(start, end)
        if length <= 0:
            return
        dx = (end[0] - start[0]) / length
        dy = (end[1] - start[1]) / length
        position = 0.0
        while position < length:
            segment_end = min(position + 14, length)
            pygame.draw.line(
                surface,
                color,
                (start[0] + dx * position, start[1] + dy * position),
                (start[0] + dx * segment_end, start[1] + dy * segment_end),
                width,
            )
            position += 23
