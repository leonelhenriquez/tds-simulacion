"""Semáforos colocados manualmente que controlan los accesos a las intersecciones."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Dict, List, Optional, Tuple

import pygame


Point = Tuple[float, float]
IntersectionKey = Tuple[int, int]


@dataclass(frozen=True)
class SignalTarget:
    """Un punto de entrada donde se puede instalar un semáforo."""

    intersection: IntersectionKey
    direction: str
    road_index: int
    stop_line: float
    draw_position: Point
    stop_segment: Tuple[Point, Point]

    @property
    def key(self) -> Tuple[IntersectionKey, str]:
        return self.intersection, self.direction


class TrafficSignalSystem:
    """Stores manually installed signals and calculates their coordinated state."""

    YELLOW_SECONDS = 2.0
    ALL_RED_SECONDS = 1.0

    COLORS = {
        "red": (240, 48, 65),
        "yellow": (255, 190, 0),
        "green": (0, 205, 125),
    }

    def __init__(self, map_generator) -> None:
        self.map_generator = map_generator
        self.targets: List[SignalTarget] = []
        self.signals: Dict[Tuple[IntersectionKey, str], SignalTarget] = {}
        self._font: Optional[pygame.font.Font] = None
        self.refresh_targets()

    def __len__(self) -> int:
        return len(self.signals)

    def clear(self) -> None:
        self.signals.clear()

    def refresh_targets(self) -> None:
        """Reconstruye ubicaciones de señales válidas a partir de la cuadrícula de intersecciones generada."""
        rw = self.map_generator.road_width
        sw = self.map_generator.sidewalk_w
        half = rw / 2
        line_gap = 3
        corner_gap = 13
        targets: List[SignalTarget] = []

        for inter in self.map_generator.get_intersections():
            key = (inter.col, inter.row)
            cx, cy = inter.cx, inter.cy

            targets.extend(
                [
                    SignalTarget(
                        key,
                        "right",
                        inter.row,
                        cx - half - line_gap,
                        (cx - half - corner_gap, cy + half - 8),
                        ((cx - half - line_gap, cy + 4), (cx - half - line_gap, cy + half - sw)),
                    ),
                    SignalTarget(
                        key,
                        "left",
                        inter.row,
                        cx + half + line_gap,
                        (cx + half + corner_gap, cy - half + 8),
                        ((cx + half + line_gap, cy - half + sw), (cx + half + line_gap, cy - 4)),
                    ),
                    SignalTarget(
                        key,
                        "down",
                        inter.col,
                        cy - half - line_gap,
                        (cx + half - 8, cy - half - corner_gap),
                        ((cx + 4, cy - half - line_gap), (cx + half - sw, cy - half - line_gap)),
                    ),
                    SignalTarget(
                        key,
                        "up",
                        inter.col,
                        cy + half + line_gap,
                        (cx - half + 8, cy + half + corner_gap),
                        ((cx - half + sw, cy + half + line_gap), (cx - 4, cy + half + line_gap)),
                    ),
                ]
            )

        self.targets = targets

    def place_near(self, position: Point) -> Optional[SignalTarget]:
        """Install a signal at the nearest incoming approach."""
        target = self._nearest(self.targets, position)
        if target is None:
            return None

        # Se acepta dejarlo cerca de una carretera o intersección; dejarlo en lo profundo del interior
        # Se ignora un bloqueo en lugar de instalar inesperadamente una señal distante.
        if self._distance(position, target.draw_position) > self.map_generator.road_width * 1.45:
            return None

        self.signals[target.key] = target
        return target

    def remove_near(self, position: Point, radius: float = 30) -> bool:
        """Remove the nearest installed signal, if it is close enough."""
        target = self._nearest(list(self.signals.values()), position)
        if target is None or self._distance(position, target.draw_position) > radius:
            return False
        del self.signals[target.key]
        return True

    def state_for(
        self, target: SignalTarget, green_seconds: float, now: Optional[float] = None
    ) -> str:
        """Return a coordinated state: horizontal and vertical approaches alternate."""
        if now is None:
            now = time.monotonic()

        green_seconds = max(1.0, green_seconds)
        section = green_seconds + self.YELLOW_SECONDS + self.ALL_RED_SECONDS
        phase = now % (section * 2)
        horizontal = target.direction in ("right", "left")

        if phase < green_seconds:
            return "green" if horizontal else "red"
        if phase < green_seconds + self.YELLOW_SECONDS:
            return "yellow" if horizontal else "red"
        if phase < section:
            return "red"
        if phase < section + green_seconds:
            return "red" if horizontal else "green"
        if phase < section + green_seconds + self.YELLOW_SECONDS:
            return "red" if horizontal else "yellow"
        return "red"

    def distance_to_stop(
        self,
        direction: str,
        lane_index: int,
        front_position: float,
        green_seconds: float,
        now: Optional[float] = None,
    ) -> float:
        """Distance to the closest red/yellow signal ahead of a vehicle."""
        road_index = lane_index // 2
        distances = []

        for target in self.signals.values():
            if target.direction != direction or target.road_index != road_index:
                continue
            if self.state_for(target, green_seconds, now) == "green":
                continue

            if direction in ("right", "down"):
                distance = target.stop_line - front_position
            else:
                distance = front_position - target.stop_line

            # Un vehículo que ya haya cruzado la línea de detención debe despejar la intersección.
            if distance >= 0:
                distances.append(distance)

        return min(distances) if distances else float("inf")

    def draw(self, surface: pygame.Surface, green_seconds: float) -> None:
        """Draw installed signals and their colored stop lines."""
        if self._font is None:
            self._font = pygame.font.SysFont("arial", 11, bold=True)

        now = time.monotonic()
        for target in self.signals.values():
            state = self.state_for(target, green_seconds, now)
            color = self.COLORS[state]
            pygame.draw.line(surface, color, target.stop_segment[0], target.stop_segment[1], 3)
            self._draw_signal_head(surface, target, state)

    def draw_targets(self, surface: pygame.Surface) -> None:
        """Show all manual placement slots while the user drags a signal."""
        for target in self.targets:
            occupied = target.key in self.signals
            color = (90, 105, 120) if occupied else (255, 184, 0)
            pygame.draw.circle(
                surface,
                color,
                (round(target.draw_position[0]), round(target.draw_position[1])),
                11,
                2,
            )

    def _draw_signal_head(
        self, surface: pygame.Surface, target: SignalTarget, active_state: str
    ) -> None:
        x, y = round(target.draw_position[0]), round(target.draw_position[1])
        housing = pygame.Rect(x - 7, y - 18, 14, 36)
        pygame.draw.rect(surface, (7, 13, 22), housing, border_radius=4)
        pygame.draw.rect(surface, (125, 137, 150), housing, 1, border_radius=4)

        for index, state in enumerate(("red", "yellow", "green")):
            color = self.COLORS[state] if state == active_state else (55, 61, 68)
            pygame.draw.circle(surface, color, (x, y - 11 + index * 11), 4)

        arrow = {"right": ">", "left": "<", "down": "v", "up": "^"}[target.direction]
        arrow_img = self._font.render(arrow, True, (245, 248, 252))
        surface.blit(arrow_img, (x - arrow_img.get_width() // 2, y + 18))

    @staticmethod
    def _nearest(targets: List[SignalTarget], position: Point) -> Optional[SignalTarget]:
        if not targets:
            return None
        return min(targets, key=lambda target: TrafficSignalSystem._distance(position, target.draw_position))

    @staticmethod
    def _distance(first: Point, second: Point) -> float:
        return math.hypot(first[0] - second[0], first[1] - second[1])
