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
    axis: str
    lateral_position: float
    clear_after: float
    accident_ids: frozenset


class TrafficAccidentSystem:
    """Generate incidents using a Poisson process and expose blocked lanes."""

    STOP_GAP = 18
    MAX_ACCIDENTS = 8
    DETOUR_TRIGGER_DISTANCE = 145
    BLOCK_INFLATE = 2
    VEHICLE_CANDIDATE_DISTANCE = 135
    CROSSING_CONFLICT_DISTANCE = 82
    CROSSING_PAIR_DISTANCE = 54
    CROSSING_COOLDOWN_FRAMES = 150

    def __init__(self, map_generator, arrivals_per_minute: float = 1.5) -> None:
        self.map_generator = map_generator
        self.arrivals_per_minute = max(0.0, arrivals_per_minute)
        self.crossing_crash_probability = 0.22
        self.accidents: Dict[int, TrafficAccident] = {}
        self._rng = random.Random()
        self._simulation_time = 0.0
        self._next_arrival = self._sample_interarrival()
        self._next_id = 1
        self._font: Optional[pygame.font.Font] = None
        self._slots: List[TrafficAccident] = []
        self._crossing_cooldowns: Dict[Tuple[int, int, IntersectionKey], int] = {}
        self.refresh_slots()

    def __len__(self) -> int:
        return len(self.accidents)

    @property
    def model_label(self) -> str:
        return f"Poisson {self.arrivals_per_minute:.1f}/min"

    def clear(self) -> None:
        self.accidents.clear()
        self._crossing_cooldowns.clear()
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
                    position = self._fallback_position(inter, spawn, direction)
                    rect = self._lane_rect(direction, position)
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

    def update(self, dt_seconds: float, active_vehicles: Iterable[object] = ()) -> List[object]:
        """Advance Poisson time and create incidents at sampled arrival times."""
        self._simulation_time += max(0.0, dt_seconds)
        if self._simulation_time < self._next_arrival:
            return []

        victims: List[object] = []
        if len(self.accidents) < self.MAX_ACCIDENTS:
            _, victims = self.generate_from_vehicles(active_vehicles, allow_slot_fallback=False)
        self._next_arrival = self._simulation_time + self._sample_interarrival()
        return victims

    def generate_from_vehicles(
        self, active_vehicles: Iterable[object], allow_slot_fallback: bool = False
    ) -> Tuple[Optional[TrafficAccident], List[object]]:
        """Create a crash from a real vehicle currently approaching an intersection."""
        vehicles = list(active_vehicles)
        candidates = []
        for vehicle in vehicles:
            data = self._candidate_from_vehicle(vehicle)
            if data is not None:
                candidates.append(data)

        self._rng.shuffle(candidates)
        for vehicle, intersection, position, rect in candidates:
            partner = self._nearby_partner(vehicle, intersection, vehicles)
            if partner is None:
                continue
            accident = TrafficAccident(
                self._next_id,
                intersection,
                vehicle.direction,
                vehicle.lane // 2,
                vehicle.lane,
                position,
                rect,
            )
            self.accidents[accident.accident_id] = accident
            self._next_id += 1
            return accident, [vehicle, partner]

        if allow_slot_fallback:
            occupied_rects = [
                vehicle._vehicle_rect()
                for vehicle in vehicles
                if hasattr(vehicle, "_vehicle_rect")
            ]
            return self.generate_random(occupied_rects), []
        return None, []

    def generate_from_crossing_conflict(
        self,
        active_vehicles: Iterable[object],
        crash_probability: Optional[float] = None,
    ) -> Tuple[Optional[TrafficAccident], List[object]]:
        """Sometimes turn a perpendicular intersection conflict into a crash."""
        if len(self.accidents) >= self.MAX_ACCIDENTS:
            return None, []

        self._tick_crossing_cooldowns()
        probability = self.crossing_crash_probability if crash_probability is None else crash_probability
        probability = max(0.0, min(1.0, probability))
        vehicles = [
            vehicle
            for vehicle in active_vehicles
            if getattr(vehicle, "alive", lambda: False)()
            and getattr(vehicle, "temporary_detour", None) is None
            and hasattr(vehicle, "_vehicle_rect")
        ]

        candidates = []
        for index, first in enumerate(vehicles):
            for second in vehicles[index + 1:]:
                data = self._crossing_conflict(first, second)
                if data is not None:
                    candidates.append(data)

        self._rng.shuffle(candidates)
        for horizontal, vertical, intersection in candidates:
            key = self._crossing_key(horizontal, vertical, intersection)
            if key in self._crossing_cooldowns:
                continue
            self._crossing_cooldowns[key] = self.CROSSING_COOLDOWN_FRAMES

            if self._rng.random() > probability:
                return None, []

            primary, secondary = self._rng.choice(
                ((horizontal, vertical), (vertical, horizontal))
            )
            if any(
                accident.slot_key == (intersection, primary.direction, primary.lane)
                for accident in self.accidents.values()
            ):
                return None, []

            rect = self._rect_from_vehicle(primary, primary._vehicle_rect())
            if self._rect_hits_other_vehicle(rect, vehicles, {primary, secondary}):
                return None, []
            if not self.position_is_clear(rect):
                return None, []

            accident = TrafficAccident(
                self._next_id,
                intersection,
                primary.direction,
                primary.lane // 2,
                primary.lane,
                rect.center,
                rect,
            )
            self.accidents[accident.accident_id] = accident
            self._next_id += 1
            return accident, [primary, secondary]

        return None, []

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
            and not any(slot.rect.inflate(4, 4).colliderect(rect) for rect in occupied)
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

    def blocking_ids_for(self, accident: TrafficAccident) -> frozenset:
        """Return all crash ids blocking the same approach as this accident."""
        first_lane = accident.road_index * 2
        lane_ids = (first_lane, first_lane + 1)
        return frozenset(
            item.accident_id
            for item in self.accidents.values()
            if item.intersection == accident.intersection
            and item.direction == accident.direction
            and item.lane_index in lane_ids
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
            "horizontal" if accident.direction in ("right", "left") else "vertical",
            lateral_position,
            clear_after,
            frozenset(item.accident_id for item in blocking),
        )

    def position_is_clear(
        self, rect: pygame.Rect, ignored_ids: Iterable[int] = ()
    ) -> bool:
        ignored = set(ignored_ids)
        return not any(
            accident.accident_id not in ignored
            and rect.colliderect(accident.rect.inflate(self.BLOCK_INFLATE, self.BLOCK_INFLATE))
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
        pygame.draw.rect(surface, (255, 102, 30), rect.inflate(4, 4), 2, border_radius=5)

        if accident.direction in ("right", "left"):
            first = pygame.Rect(rect.x, rect.centery - 5, min(20, rect.width), 10)
            second = pygame.Rect(rect.right - min(20, rect.width), rect.centery - 5, min(20, rect.width), 10)
        else:
            first = pygame.Rect(rect.centerx - 5, rect.y, 10, min(20, rect.height))
            second = pygame.Rect(rect.centerx - 5, rect.bottom - min(20, rect.height), 10, min(20, rect.height))

        pygame.draw.rect(surface, (205, 45, 55), first, border_radius=4)
        pygame.draw.rect(surface, (90, 120, 155), second, border_radius=4)
        pygame.draw.line(surface, (255, 224, 90), rect.topleft, rect.bottomright, 3)
        pygame.draw.line(surface, (255, 224, 90), rect.topright, rect.bottomleft, 3)

        for offset, radius in ((0, 5), (7, 4), (13, 3)):
            pygame.draw.circle(
                surface,
                (105 + offset * 3, 105 + offset * 3, 105 + offset * 3),
                (rect.centerx + offset, rect.top - 6 - offset),
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

    def _candidate_from_vehicle(self, vehicle) -> Optional[Tuple[object, IntersectionKey, Point, pygame.Rect]]:
        if not getattr(vehicle, "alive", lambda: False)():
            return None
        if getattr(vehicle, "temporary_detour", None) is not None:
            return None

        direction = vehicle.direction
        road_index = vehicle.lane // 2
        rect = vehicle._vehicle_rect()
        center = rect.center
        intersections = [
            inter
            for inter in self.map_generator.get_intersections()
            if (inter.row == road_index if direction in ("right", "left") else inter.col == road_index)
        ]
        if not intersections:
            return None

        if direction in ("right", "left"):
            nearest = min(intersections, key=lambda inter: abs(center[0] - inter.cx))
            distance = abs(center[0] - nearest.cx)
        else:
            nearest = min(intersections, key=lambda inter: abs(center[1] - inter.cy))
            distance = abs(center[1] - nearest.cy)

        if distance > self.VEHICLE_CANDIDATE_DISTANCE:
            return None

        intersection = (nearest.col, nearest.row)
        if any(accident.slot_key == (intersection, direction, vehicle.lane) for accident in self.accidents.values()):
            return None

        accident_rect = self._rect_from_vehicle(vehicle, rect)
        if not self.position_is_clear(accident_rect):
            return None

        position = accident_rect.center
        return vehicle, intersection, position, accident_rect

    def _nearby_partner(
        self, primary, intersection: IntersectionKey, vehicles: List[object]
    ) -> Optional[object]:
        primary_rect = primary._vehicle_rect()
        partners = []
        for other in vehicles:
            if other is primary:
                continue
            if getattr(other, "direction", None) != primary.direction:
                continue
            if getattr(other, "lane", None) != primary.lane:
                continue
            if not getattr(other, "alive", lambda: False)():
                continue
            if getattr(other, "temporary_detour", None) is not None:
                continue
            if not hasattr(other, "_vehicle_rect"):
                continue

            other_data = self._candidate_from_vehicle(other)
            if other_data is None or other_data[1] != intersection:
                continue

            distance = math.dist(primary_rect.center, other._vehicle_rect().center)
            if distance <= self.map_generator.road_width * 1.8:
                partners.append((distance, other))

        if not partners:
            return None
        return min(partners, key=lambda item: item[0])[1]

    def _crossing_conflict(
        self, first, second
    ) -> Optional[Tuple[object, object, IntersectionKey]]:
        first_axis = self._axis(first.direction)
        second_axis = self._axis(second.direction)
        if first_axis == second_axis:
            return None

        horizontal = first if first_axis == "horizontal" else second
        vertical = second if first_axis == "horizontal" else first
        intersection = (vertical.lane // 2, horizontal.lane // 2)
        if not self._intersection_exists(intersection):
            return None

        inter = self._intersection_by_key(intersection)
        h_center = horizontal._vehicle_rect().center
        v_center = vertical._vehicle_rect().center
        if abs(h_center[0] - inter.cx) > self.CROSSING_CONFLICT_DISTANCE:
            return None
        if abs(v_center[1] - inter.cy) > self.CROSSING_CONFLICT_DISTANCE:
            return None
        if abs(h_center[1] - inter.cy) > self.map_generator.road_width * 0.55:
            return None
        if abs(v_center[0] - inter.cx) > self.map_generator.road_width * 0.55:
            return None
        if math.dist(h_center, v_center) > self.CROSSING_PAIR_DISTANCE:
            return None
        return horizontal, vertical, intersection

    def _rect_hits_other_vehicle(
        self, rect: pygame.Rect, vehicles: List[object], victims: Set[object]
    ) -> bool:
        blocked = rect.inflate(4, 4)
        for vehicle in vehicles:
            if vehicle in victims:
                continue
            if blocked.colliderect(vehicle._vehicle_rect()):
                return True
        return False

    def _tick_crossing_cooldowns(self) -> None:
        expired = []
        for key, frames in list(self._crossing_cooldowns.items()):
            frames -= 1
            if frames <= 0:
                expired.append(key)
            else:
                self._crossing_cooldowns[key] = frames
        for key in expired:
            del self._crossing_cooldowns[key]

    def _intersection_exists(self, key: IntersectionKey) -> bool:
        return any((inter.col, inter.row) == key for inter in self.map_generator.get_intersections())

    def _intersection_by_key(self, key: IntersectionKey):
        return next(
            inter
            for inter in self.map_generator.get_intersections()
            if (inter.col, inter.row) == key
        )

    @staticmethod
    def _crossing_key(first, second, intersection: IntersectionKey) -> Tuple[int, int, IntersectionKey]:
        first_id, second_id = sorted((id(first), id(second)))
        return first_id, second_id, intersection

    @staticmethod
    def _axis(direction: str) -> str:
        return "horizontal" if direction in ("right", "left") else "vertical"

    def _rect_from_vehicle(self, vehicle, vehicle_rect: pygame.Rect) -> pygame.Rect:
        center_x, center_y = vehicle_rect.center
        if vehicle.direction in ("right", "left"):
            width = max(22, min(32, vehicle_rect.width + 6))
            height = max(10, min(14, vehicle_rect.height + 2))
        else:
            width = max(10, min(14, vehicle_rect.width + 2))
            height = max(22, min(32, vehicle_rect.height + 6))
        return pygame.Rect(round(center_x - width / 2), round(center_y - height / 2), width, height)

    def _fallback_position(self, inter, spawn, direction: str) -> Point:
        offset = self.map_generator.road_width / 2 + 24
        if direction == "right":
            return inter.cx - offset, spawn.spawn_y
        if direction == "left":
            return inter.cx + offset, spawn.spawn_y
        if direction == "down":
            return spawn.spawn_x, inter.cy - offset
        return spawn.spawn_x, inter.cy + offset

    def _lane_rect(self, direction: str, position: Point) -> pygame.Rect:
        x, y = position
        if direction in ("right", "left"):
            return pygame.Rect(round(x - 15), round(y - 7), 30, 14)
        return pygame.Rect(round(x - 7), round(y - 15), 14, 30)

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
