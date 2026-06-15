"""Poisson traffic-accident generation and temporary bypass management."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Dict, Iterable, List, Optional, Set, Tuple

import pygame


Point = Tuple[float, float]
IntersectionKey = Tuple[int, int]


@dataclass(frozen=True)
class TrafficAccident:
    accident_id: int
    intersection: IntersectionKey
    direction: str
    road_index: int
    lane_index: int
    position: Point
    rect: pygame.Rect

    @property
    def slot_key(self) -> Tuple[IntersectionKey, str, int]:
        return self.intersection, self.direction, self.lane_index


@dataclass(frozen=True)
class TemporaryDetour:
    intersection: IntersectionKey
    direction: str
    road_index: int
    lateral_position: float
    clear_after: float
    accident_ids: frozenset


class TrafficAccidentSystem:
    """Generate incidents using a Poisson process and expose blocked lanes."""

    STOP_GAP = 18
    MAX_ACCIDENTS = 8
    DETOUR_TRIGGER_DISTANCE = 145

    def __init__(self, map_generator, arrivals_per_minute: float = 1.5) -> None:
        self.map_generator = map_generator
        self.arrivals_per_minute = max(0.0, arrivals_per_minute)
        self.accidents: Dict[int, TrafficAccident] = {}
        self._rng = random.Random()
        self._simulation_time = 0.0
        self._next_arrival = self._sample_interarrival()
        self._next_id = 1
        self._font: Optional[pygame.font.Font] = None
        self._slots: List[TrafficAccident] = []
        self.refresh_slots()

    def __len__(self) -> int:
        return len(self.accidents)

    @property
    def model_label(self) -> str:
        return f"Poisson {self.arrivals_per_minute:.1f}/min"

    def clear(self) -> None:
        self.accidents.clear()
        self._simulation_time = 0.0
        self._next_arrival = self._sample_interarrival()

    def refresh_slots(self) -> None:
        """Build every possible intersection/lane accident location."""
        slots: List[TrafficAccident] = []
        accident_id = -1
        spawn_by_direction = {"right": [], "left": [], "up": [], "down": []}
        for spawn in self.map_generator.get_spawn_points():
            spawn_by_direction[spawn.direction].append(spawn)

        for inter in self.map_generator.get_intersections():
            for direction in ("right", "left", "down", "up"):
                road_index = inter.row if direction in ("right", "left") else inter.col
                for lane_index in (road_index * 2, road_index * 2 + 1):
                    spawn = spawn_by_direction[direction][lane_index]
                    if direction in ("right", "left"):
                        position = (inter.cx, spawn.spawn_y)
                        rect = pygame.Rect(round(inter.cx - 19), round(spawn.spawn_y - 9), 38, 18)
                    else:
                        position = (spawn.spawn_x, inter.cy)
                        rect = pygame.Rect(round(spawn.spawn_x - 9), round(inter.cy - 19), 18, 38)
                    slots.append(
                        TrafficAccident(
                            accident_id,
                            (inter.col, inter.row),
                            direction,
                            road_index,
                            lane_index,
                            position,
                            rect,
                        )
                    )
                    accident_id -= 1
        self._slots = slots

    def update(self, dt_seconds: float, occupied_rects: Iterable[pygame.Rect] = ()) -> None:
        """Advance Poisson time and create incidents at sampled arrival times."""
        self._simulation_time += max(0.0, dt_seconds)
        if self._simulation_time < self._next_arrival:
            return

        if len(self.accidents) < self.MAX_ACCIDENTS:
            self.generate_random(occupied_rects)
        self._next_arrival = self._simulation_time + self._sample_interarrival()

    def generate_random(
        self, occupied_rects: Iterable[pygame.Rect] = ()
    ) -> Optional[TrafficAccident]:
        """Use Monte Carlo sampling to choose a currently available slot."""
        occupied = list(occupied_rects)
        used_slots = {accident.slot_key for accident in self.accidents.values()}
        candidates = [
            slot
            for slot in self._slots
            if slot.slot_key not in used_slots
            and not any(slot.rect.inflate(8, 8).colliderect(rect) for rect in occupied)
        ]
        if not candidates:
            return None

        sampled = self._rng.choice(candidates)
        accident = TrafficAccident(
            self._next_id,
            sampled.intersection,
            sampled.direction,
            sampled.road_index,
            sampled.lane_index,
            sampled.position,
            sampled.rect.copy(),
        )
        self.accidents[accident.accident_id] = accident
        self._next_id += 1
        return accident

    def create_at(
        self, intersection: IntersectionKey, direction: str, lane_index: int
    ) -> Optional[TrafficAccident]:
        """Create a deterministic accident; useful for demos and tests."""
        for slot in self._slots:
            if (
                slot.intersection == intersection
                and slot.direction == direction
                and slot.lane_index == lane_index
            ):
                if any(existing.slot_key == slot.slot_key for existing in self.accidents.values()):
                    return None
                accident = TrafficAccident(
                    self._next_id,
                    slot.intersection,
                    slot.direction,
                    slot.road_index,
                    slot.lane_index,
                    slot.position,
                    slot.rect.copy(),
                )
                self.accidents[accident.accident_id] = accident
                self._next_id += 1
                return accident
        return None

    def remove_near(self, position: Point, radius: float = 35) -> bool:
        """Remove a crash manually when the user right-clicks near it."""
        if not self.accidents:
            return False
        closest = min(
            self.accidents.values(),
            key=lambda accident: math.dist(position, accident.position),
        )
        if math.dist(position, closest.position) > radius:
            return False
        del self.accidents[closest.accident_id]
        return True

    def nearest_block(
        self,
        direction: str,
        lane_index: int,
        front_position: float,
        ignored_ids: Iterable[int] = (),
    ) -> Tuple[float, Optional[TrafficAccident]]:
        """Return distance to the nearest crash blocking the current lane."""
        ignored = set(ignored_ids)
        nearest_distance = float("inf")
        nearest_accident = None

        for accident in self.accidents.values():
            if (
                accident.accident_id in ignored
                or accident.direction != direction
                or accident.lane_index != lane_index
            ):
                continue

            if direction == "right":
                distance = accident.rect.left - self.STOP_GAP - front_position
            elif direction == "left":
                distance = front_position - accident.rect.right - self.STOP_GAP
            elif direction == "down":
                distance = accident.rect.top - self.STOP_GAP - front_position
            else:
                distance = front_position - accident.rect.bottom - self.STOP_GAP

            if 0 <= distance < nearest_distance:
                nearest_distance = distance
                nearest_accident = accident

        return nearest_distance, nearest_accident

    def lane_blocked_at(
        self, intersection: IntersectionKey, direction: str, lane_index: int
    ) -> bool:
        return any(
            accident.intersection == intersection
            and accident.direction == direction
            and accident.lane_index == lane_index
            for accident in self.accidents.values()
        )

    def detour_for(self, accident: TrafficAccident) -> Optional[TemporaryDetour]:
        """Return an unofficial bypass only when both same-direction lanes are blocked."""
        first_lane = accident.road_index * 2
        lane_ids = (first_lane, first_lane + 1)
        blocking = [
            item
            for item in self.accidents.values()
            if item.intersection == accident.intersection
            and item.direction == accident.direction
            and item.lane_index in lane_ids
        ]
        if {item.lane_index for item in blocking} != set(lane_ids):
            return None

        lateral_position = self._detour_lateral_position(accident.direction, accident.road_index)
        center = accident.position[0] if accident.direction in ("right", "left") else accident.position[1]
        clearance = self.map_generator.road_width * 0.95
        clear_after = center + clearance if accident.direction in ("right", "down") else center - clearance
        return TemporaryDetour(
            accident.intersection,
            accident.direction,
            accident.road_index,
            lateral_position,
            clear_after,
            frozenset(item.accident_id for item in blocking),
        )

    def position_is_clear(self, rect: pygame.Rect) -> bool:
        return not any(
            rect.colliderect(accident.rect.inflate(8, 8))
            for accident in self.accidents.values()
        )

    def draw(self, surface: pygame.Surface) -> None:
        if self._font is None:
            self._font = pygame.font.SysFont("arial", 11, bold=True)

        self._draw_temporary_detours(surface)
        for accident in self.accidents.values():
            self._draw_accident(surface, accident)

    def _draw_accident(self, surface: pygame.Surface, accident: TrafficAccident) -> None:
        rect = accident.rect
        pygame.draw.rect(surface, (255, 102, 30), rect.inflate(6, 6), 2, border_radius=5)

        if accident.direction in ("right", "left"):
            first = pygame.Rect(rect.x, rect.centery - 6, 24, 12)
            second = pygame.Rect(rect.right - 24, rect.centery - 6, 24, 12)
        else:
            first = pygame.Rect(rect.centerx - 6, rect.y, 12, 24)
            second = pygame.Rect(rect.centerx - 6, rect.bottom - 24, 12, 24)

        pygame.draw.rect(surface, (205, 45, 55), first, border_radius=4)
        pygame.draw.rect(surface, (90, 120, 155), second, border_radius=4)
        pygame.draw.line(surface, (255, 224, 90), rect.topleft, rect.bottomright, 3)
        pygame.draw.line(surface, (255, 224, 90), rect.topright, rect.bottomleft, 3)

        for offset, radius in ((0, 5), (7, 4), (13, 3)):
            pygame.draw.circle(
                surface,
                (105 + offset * 3, 105 + offset * 3, 105 + offset * 3),
                (rect.centerx + offset, rect.top - 7 - offset),
                radius,
            )

    def _draw_temporary_detours(self, surface: pygame.Surface) -> None:
        drawn: Set[Tuple[IntersectionKey, str]] = set()
        for accident in self.accidents.values():
            detour = self.detour_for(accident)
            if detour is None:
                continue
            key = (detour.intersection, detour.direction)
            if key in drawn:
                continue
            drawn.add(key)

            inter = next(
                item
                for item in self.map_generator.get_intersections()
                if (item.col, item.row) == detour.intersection
            )
            reach = self.map_generator.road_width * 1.45
            if detour.direction in ("right", "left"):
                start = (inter.cx - reach, detour.lateral_position)
                end = (inter.cx + reach, detour.lateral_position)
                label_pos = (inter.cx - 40, detour.lateral_position + 6)
            else:
                start = (detour.lateral_position, inter.cy - reach)
                end = (detour.lateral_position, inter.cy + reach)
                label_pos = (detour.lateral_position + 7, inter.cy - 8)

            self._dashed_line(surface, (255, 126, 30), start, end)
            label = self._font.render("VIA TEMPORAL", True, (255, 225, 190))
            surface.blit(label, label_pos)

    def _detour_lateral_position(self, direction: str, road_index: int) -> float:
        points = [
            spawn
            for spawn in self.map_generator.get_spawn_points()
            if spawn.direction == direction and spawn.lane // 2 == road_index
        ]
        offset = 22
        if direction == "right":
            return max(point.spawn_y for point in points) + offset
        if direction == "left":
            return min(point.spawn_y for point in points) - offset
        if direction == "down":
            return max(point.spawn_x for point in points) + offset
        return min(point.spawn_x for point in points) - offset

    def _sample_interarrival(self) -> float:
        rate_per_second = self.arrivals_per_minute / 60
        if rate_per_second <= 0:
            return float("inf")
        return self._rng.expovariate(rate_per_second)

    @staticmethod
    def _dashed_line(
        surface: pygame.Surface, color: Tuple[int, int, int], start: Point, end: Point
    ) -> None:
        length = math.dist(start, end)
        if length <= 0:
            return
        dx = (end[0] - start[0]) / length
        dy = (end[1] - start[1]) / length
        position = 0.0
        while position < length:
            segment_end = min(position + 12, length)
            pygame.draw.line(
                surface,
                color,
                (start[0] + dx * position, start[1] + dy * position),
                (start[0] + dx * segment_end, start[1] + dy * segment_end),
                3,
            )
            position += 20
