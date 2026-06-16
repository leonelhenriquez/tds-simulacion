"""Manual unofficial routes that vehicles can use as temporary detours."""

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
    lateral_position: float
    start: Point
    end: Point

    @property
    def center(self) -> Point:
        return ((self.start[0] + self.end[0]) / 2, (self.start[1] + self.end[1]) / 2)


class ManualExtraRouteSystem:
    """Stores user-placed unofficial routes drawn over roads or non-road areas."""

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
        for inter in self.map_generator.get_intersections():
            self._horizontal_roads[inter.row] = inter.cy
            self._vertical_roads[inter.col] = inter.cx

    def place_near(self, position: Point) -> ManualExtraRoute:
        """Add a route at any map position, linked to the nearest street axis."""
        x, y = position
        horizontal = min(
            self._horizontal_roads.items(), key=lambda item: abs(y - item[1])
        )
        vertical = min(
            self._vertical_roads.items(), key=lambda item: abs(x - item[1])
        )

        length = self.map_generator.road_width * 3.2
        if abs(y - horizontal[1]) <= abs(x - vertical[1]):
            start = (max(0, x - length / 2), y)
            end = (min(self.map_generator.total_width, x + length / 2), y)
            route = ManualExtraRoute(
                self._next_id, "horizontal", horizontal[0], y, start, end
            )
        else:
            start = (x, max(0, y - length / 2))
            end = (x, min(self.map_generator.total_height, y + length / 2))
            route = ManualExtraRoute(
                self._next_id, "vertical", vertical[0], x, start, end
            )

        self.routes.append(route)
        self._next_id += 1
        return route

    def detour_for(self, accident) -> Optional[TemporaryDetour]:
        axis = "horizontal" if accident.direction in ("right", "left") else "vertical"
        candidates = [
            route
            for route in self.routes
            if route.axis == axis
            and route.road_index == accident.road_index
            and self._route_spans_accident(route, accident)
        ]
        if not candidates:
            return None

        route = min(
            candidates,
            key=lambda item: abs(item.lateral_position - self._accident_lateral(accident)),
        )
        if accident.direction == "right":
            clear_after = route.end[0]
        elif accident.direction == "left":
            clear_after = route.start[0]
        elif accident.direction == "down":
            clear_after = route.end[1]
        else:
            clear_after = route.start[1]

        return TemporaryDetour(
            accident.intersection,
            accident.direction,
            accident.road_index,
            route.lateral_position,
            clear_after,
            frozenset((accident.accident_id,)),
        )

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
            label = self._font.render("RUTA EXTRA", True, (255, 226, 190))
            cx, cy = route.center
            surface.blit(label, (cx - label.get_width() / 2, cy + 8))

    def _route_spans_accident(self, route: ManualExtraRoute, accident) -> bool:
        margin = self.map_generator.road_width * 0.8
        if route.axis == "horizontal":
            left, right = sorted((route.start[0], route.end[0]))
            return left - margin <= accident.position[0] <= right + margin
        top, bottom = sorted((route.start[1], route.end[1]))
        return top - margin <= accident.position[1] <= bottom + margin

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
