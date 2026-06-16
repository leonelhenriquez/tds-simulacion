"""Scrollable control panel used by the traffic simulation."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import pygame


Color = Tuple[int, int, int]

PANEL_BG: Color = (29, 40, 56)
CARD_BG: Color = (14, 24, 40)
CARD_BORDER: Color = (55, 72, 94)
TEXT: Color = (245, 248, 252)
MUTED: Color = (168, 187, 214)
INPUT_BG: Color = (30, 43, 62)
WHITE: Color = (248, 250, 252)
BLUE: Color = (47, 139, 255)
YELLOW: Color = (255, 184, 0)
GREEN: Color = (0, 204, 130)
RED: Color = (255, 50, 76)


class ControlPanel:
    """Draws and manages a fixed-width, vertically scrollable side panel."""

    WIDTH = 306
    CONTENT_HEIGHT = 1710
    VEHICLE_OPTIONS = ("Aleatorio", "Sedán", "Motocicleta", "Carga", "Bus")
    VEHICLE_KEYS = {
        "Aleatorio": "random",
        "Sedán": "car",
        "Motocicleta": "motorcycle",
        "Carga": "truck",
        "Bus": "bus",
    }

    def __init__(self) -> None:
        self.scroll_y = 0
        self.max_vehicles = 46
        self.speed_multiplier = 1.0
        self.signal_seconds = 8
        self.vehicle_type = "Aleatorio"

        self._panel_rect = pygame.Rect(0, 0, self.WIDTH, 600)
        self._controls: Dict[str, pygame.Rect] = {}
        self._dropdown_options: Dict[str, pygame.Rect] = {}
        self._dropdown_open = False
        self._active_slider: Optional[str] = None
        self._drag_payload: Optional[str] = None
        self._mouse_pos = (0, 0)

        self.font_title = pygame.font.SysFont("arial", 20, bold=True)
        self.font_heading = pygame.font.SysFont("arial", 16)
        self.font_body = pygame.font.SysFont("arial", 14)
        self.font_small = pygame.font.SysFont("arial", 12)
        self.font_button = pygame.font.SysFont("arial", 14, bold=True)

    @property
    def selected_vehicle_key(self) -> str:
        return self.VEHICLE_KEYS[self.vehicle_type]

    @property
    def drag_payload(self) -> Optional[str]:
        return self._drag_payload

    def _max_scroll(self) -> int:
        return max(0, self.CONTENT_HEIGHT - self._panel_rect.height)

    def _content_pos(self, screen_pos: Tuple[int, int]) -> Tuple[int, int]:
        return (
            screen_pos[0] - self._panel_rect.x,
            screen_pos[1] - self._panel_rect.y + self.scroll_y,
        )

    def _screen_rect(self, content_rect: pygame.Rect) -> pygame.Rect:
        return content_rect.move(
            self._panel_rect.x, self._panel_rect.y - self.scroll_y
        )

    def _set_slider_value(self, name: str, content_x: int) -> None:
        rect = self._controls[name]
        ratio = max(0.0, min(1.0, (content_x - rect.x) / rect.width))
        if name == "vehicle_slider":
            self.max_vehicles = round(ratio * 100)
        elif name == "speed_slider":
            self.speed_multiplier = round(0.5 + ratio * 1.5, 1)
        elif name == "signal_slider":
            self.signal_seconds = round(3 + ratio * 27)

    def handle_event(self, event: pygame.event.Event) -> Optional[dict]:
        """Handle a Pygame event and optionally return an action for the map."""
        if hasattr(event, "pos"):
            self._mouse_pos = event.pos

        if self._drag_payload is not None:
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                payload = self._drag_payload
                self._drag_payload = None
                if not self._panel_rect.collidepoint(event.pos):
                    return {"action": f"drop_{payload}", "pos": event.pos}
                return {"action": "cancel_drag"}
            return {"action": "dragging"}

        if event.type == pygame.MOUSEWHEEL:
            mouse_pos = pygame.mouse.get_pos()
            if self._panel_rect.collidepoint(mouse_pos):
                self.scroll_y = max(
                    0, min(self._max_scroll(), self.scroll_y - event.y * 42)
                )
                return {"action": "panel_scrolled"}

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._active_slider = None

        if event.type == pygame.MOUSEMOTION and self._active_slider:
            content_x, _ = self._content_pos(event.pos)
            self._set_slider_value(self._active_slider, content_x)
            return {"action": "panel_changed"}

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        if not self._panel_rect.collidepoint(event.pos):
            self._dropdown_open = False
            return None

        point = self._content_pos(event.pos)

        if self._dropdown_open:
            for option, rect in self._dropdown_options.items():
                if rect.collidepoint(point):
                    self.vehicle_type = option
                    self._dropdown_open = False
                    return {"action": "panel_changed"}
            if not self._controls.get("vehicle_dropdown", pygame.Rect(0, 0, 0, 0)).collidepoint(point):
                self._dropdown_open = False

        for name in ("vehicle_slider", "speed_slider", "signal_slider"):
            if self._controls.get(name, pygame.Rect(0, 0, 0, 0)).inflate(0, 18).collidepoint(point):
                self._active_slider = name
                self._set_slider_value(name, point[0])
                return {"action": "panel_changed"}

        if self._controls.get("decrease", pygame.Rect(0, 0, 0, 0)).collidepoint(point):
            self.max_vehicles = max(0, self.max_vehicles - 1)
            return {"action": "panel_changed"}
        if self._controls.get("increase", pygame.Rect(0, 0, 0, 0)).collidepoint(point):
            self.max_vehicles = min(100, self.max_vehicles + 1)
            return {"action": "panel_changed"}
        if self._controls.get("vehicle_dropdown", pygame.Rect(0, 0, 0, 0)).collidepoint(point):
            self._dropdown_open = not self._dropdown_open
            return {"action": "panel_changed"}
        if self._controls.get("drag_vehicle", pygame.Rect(0, 0, 0, 0)).collidepoint(point):
            self._drag_payload = "vehicle"
            return {"action": "dragging"}
        if self._controls.get("drag_signal", pygame.Rect(0, 0, 0, 0)).collidepoint(point):
            self._drag_payload = "signal"
            return {"action": "dragging"}
        if self._controls.get("drag_route", pygame.Rect(0, 0, 0, 0)).collidepoint(point):
            self._drag_payload = "route"
            return {"action": "dragging"}
        if self._controls.get("reset", pygame.Rect(0, 0, 0, 0)).collidepoint(point):
            return {"action": "reset"}
        return {"action": "panel_clicked"}

    def draw(
        self,
        surface: pygame.Surface,
        panel_rect: pygame.Rect,
        stats: dict,
    ) -> None:
        self._panel_rect = panel_rect.copy()
        self.scroll_y = min(self.scroll_y, self._max_scroll())
        self._controls.clear()
        self._dropdown_options.clear()

        content = pygame.Surface((panel_rect.width, self.CONTENT_HEIGHT))
        content.fill(PANEL_BG)

        self._draw_header(content)
        self._draw_counts(content, stats)
        self._draw_add_elements(content)
        self._draw_flow(content)
        self._draw_routes(content)
        self._draw_signals(content)
        self._draw_information(content, stats)
        if self._dropdown_open:
            self._draw_dropdown_options(content)

        visible = pygame.Rect(0, self.scroll_y, panel_rect.width, panel_rect.height)
        surface.blit(content, panel_rect.topleft, visible)
        pygame.draw.line(
            surface,
            CARD_BORDER,
            panel_rect.topleft,
            panel_rect.bottomleft,
            1,
        )
        self._draw_scrollbar(surface)

    def draw_drag_preview(self, surface: pygame.Surface) -> None:
        if not self._drag_payload:
            return
        x, y = self._mouse_pos
        if self._drag_payload == "vehicle":
            pygame.draw.rect(surface, BLUE, (x - 15, y - 7, 30, 14), border_radius=5)
            pygame.draw.circle(surface, (12, 24, 40), (x - 8, y + 7), 4)
            pygame.draw.circle(surface, (12, 24, 40), (x + 8, y + 7), 4)
        elif self._drag_payload == "signal":
            pygame.draw.circle(surface, YELLOW, (x, y), 12, 3)
            pygame.draw.circle(surface, RED, (x, y - 4), 3)
            pygame.draw.circle(surface, GREEN, (x, y + 4), 3)
        else:
            pygame.draw.line(surface, YELLOW, (x - 28, y), (x + 28, y), 4)
            pygame.draw.line(surface, PANEL_BG, (x - 18, y), (x - 8, y), 2)
            pygame.draw.line(surface, PANEL_BG, (x + 8, y), (x + 18, y), 2)

    def _draw_header(self, surf: pygame.Surface) -> None:
        pygame.draw.line(surf, CARD_BORDER, (0, 62), (surf.get_width(), 62), 1)
        pygame.draw.circle(surf, TEXT, (21, 30), 8, 2)
        pygame.draw.circle(surf, PANEL_BG, (21, 30), 3)
        surf.blit(self.font_title.render("Panel de control", True, TEXT), (39, 20))

    def _card(self, surf: pygame.Surface, y: int, height: int, title: str) -> pygame.Rect:
        rect = pygame.Rect(11, y, surf.get_width() - 23, height)
        pygame.draw.rect(surf, CARD_BG, rect, border_radius=14)
        pygame.draw.rect(surf, CARD_BORDER, rect, 1, border_radius=14)
        surf.blit(self.font_heading.render(title, True, TEXT), (28, y + 20))
        return rect

    def _draw_counts(self, surf: pygame.Surface, stats: dict) -> None:
        self._card(surf, 79, 281, "Conteo de vehículos")
        labels = (
            ("Total:", stats.get("total", 0)),
            ("Sedanes:", stats.get("cars", 0)),
            ("Motos:", stats.get("motorcycles", 0)),
            ("Carga:", stats.get("trucks", 0)),
            ("Buses:", stats.get("buses", 0)),
            ("Semáforos:", stats.get("signals", 0)),
            ("Congestión:", f"{stats.get('congestion', 0)}%"),
        )
        y = 160
        for label, value in labels:
            surf.blit(self.font_body.render(label, True, TEXT), (28, y))
            value_img = self.font_body.render(str(value), True, TEXT)
            surf.blit(value_img, (266 - value_img.get_width(), y))
            y += 28

    def _draw_add_elements(self, surf: pygame.Surface) -> None:
        self._card(surf, 380, 306, "+  Agregar elementos")
        vehicle = pygame.Rect(28, 458, 238, 48)
        signal = pygame.Rect(28, 518, 238, 48)
        route = pygame.Rect(28, 578, 238, 48)
        self._controls["drag_vehicle"] = vehicle
        self._controls["drag_signal"] = signal
        self._controls["drag_route"] = route
        self._dashed_button(surf, vehicle, BLUE, "Arrastrar vehículo", "vehicle")
        self._dashed_button(surf, signal, YELLOW, "Arrastrar semáforo", "signal")
        self._dashed_button(surf, route, YELLOW, "Agregar ruta extra oficial", "route")
        help_lines = (
            "Semáforos: coloca uno en cada acceso.",
            "Clic derecho elimina choques/rutas/semáforos.",
        )
        for index, line in enumerate(help_lines):
            surf.blit(self.font_small.render(line, True, MUTED), (28, 640 + index * 17))

    def _dashed_button(
        self, surf: pygame.Surface, rect: pygame.Rect, color: Color, label: str, icon: str
    ) -> None:
        self._dashed_rect(surf, rect, color)
        if icon == "vehicle":
            pygame.draw.rect(surf, color, (43, rect.y + 18, 16, 8), 2, border_radius=3)
            pygame.draw.circle(surf, color, (47, rect.y + 28), 2)
            pygame.draw.circle(surf, color, (56, rect.y + 28), 2)
        elif icon == "signal":
            pygame.draw.circle(surf, color, (51, rect.y + 24), 8, 2)
            pygame.draw.circle(surf, color, (51, rect.y + 24), 2)
        else:
            pygame.draw.line(surf, color, (43, rect.y + 24), (60, rect.y + 24), 3)
            pygame.draw.circle(surf, color, (44, rect.y + 24), 3)
            pygame.draw.circle(surf, color, (60, rect.y + 24), 3)
        surf.blit(self.font_body.render(label, True, color), (70, rect.y + 16))

    def _draw_flow(self, surf: pygame.Surface) -> None:
        self._card(surf, 706, 274, "Flujo y velocidad")
        surf.blit(self.font_body.render("Vehículos activos", True, TEXT), (28, 768))
        self._badge(surf, str(self.max_vehicles), 235, 762)
        slider = pygame.Rect(28, 798, 238, 8)
        self._controls["vehicle_slider"] = slider
        self._slider(surf, slider, self.max_vehicles / 100)

        decrease = pygame.Rect(28, 826, 114, 34)
        increase = pygame.Rect(151, 826, 115, 34)
        self._controls["decrease"] = decrease
        self._controls["increase"] = increase
        self._button(surf, decrease, "Disminuir")
        self._button(surf, increase, "Aumentar")

        surf.blit(self.font_body.render("Velocidad", True, TEXT), (28, 885))
        self._badge(surf, f"{self.speed_multiplier:.1f}x", 228, 879, width=38)
        speed_slider = pygame.Rect(28, 915, 238, 8)
        self._controls["speed_slider"] = speed_slider
        self._slider(surf, speed_slider, (self.speed_multiplier - 0.5) / 1.5)

    def _draw_routes(self, surf: pygame.Surface) -> None:
        self._card(surf, 1000, 218, "Vehículos y rutas")
        surf.blit(self.font_body.render("Tipo de vehículo", True, TEXT), (28, 1058))
        dropdown = pygame.Rect(28, 1084, 238, 40)
        self._controls["vehicle_dropdown"] = dropdown
        pygame.draw.rect(surf, INPUT_BG, dropdown, border_radius=7)
        pygame.draw.rect(surf, CARD_BORDER, dropdown, 1, border_radius=7)
        surf.blit(self.font_body.render(self.vehicle_type, True, TEXT), (45, 1097))
        pygame.draw.lines(
            surf,
            TEXT,
            False,
            [(252, 1100), (256, 1104), (260, 1100)],
            2,
        )
        lines = (
            "La dirección se calcula según la vía.",
            "Arrastra un vehículo para colocarlo.",
        )
        for index, line in enumerate(lines):
            surf.blit(self.font_small.render(line, True, MUTED), (28, 1142 + index * 18))

    def _draw_signals(self, surf: pygame.Surface) -> None:
        self._card(surf, 1238, 177, "Semáforos")
        surf.blit(self.font_body.render("Tiempo rojo/verde", True, TEXT), (28, 1293))
        self._badge(surf, f"{self.signal_seconds}s", 235, 1287)
        slider = pygame.Rect(28, 1323, 238, 8)
        self._controls["signal_slider"] = slider
        self._slider(surf, slider, (self.signal_seconds - 3) / 27)
        self._legend_dot(surf, RED, "Rojo", 28, 1357)
        self._legend_dot(surf, YELLOW, "Amarillo", 89, 1357)
        self._legend_dot(surf, GREEN, "Verde", 178, 1357)

    def _draw_information(self, surf: pygame.Surface, stats: dict) -> None:
        y = 1435
        self._card(surf, y, 255, "Información")
        rows = (
            ("Intersecciones:", stats.get("intersections", 0)),
            ("Vías:", stats.get("roads", 0)),
            ("Rutas extra:", stats.get("extra_routes", 0)),
            ("Choques:", stats.get("accidents", 0)),
            ("Modelo:", stats.get("accident_model", "Poisson")),
        )
        row_y = y + 62
        for label, value in rows:
            surf.blit(self.font_body.render(label, True, TEXT), (28, row_y))
            value_img = self.font_body.render(str(value), True, MUTED)
            surf.blit(value_img, (266 - value_img.get_width(), row_y))
            row_y += 28
        reset = pygame.Rect(28, y + 190, 238, 42)
        self._controls["reset"] = reset
        self._button(surf, reset, "Reiniciar mapa")

    def _draw_dropdown_options(self, surf: pygame.Surface) -> None:
        base = self._controls["vehicle_dropdown"]
        menu = pygame.Rect(base.x, base.bottom + 4, base.width, len(self.VEHICLE_OPTIONS) * 34)
        pygame.draw.rect(surf, INPUT_BG, menu, border_radius=7)
        pygame.draw.rect(surf, BLUE, menu, 1, border_radius=7)
        for index, option in enumerate(self.VEHICLE_OPTIONS):
            rect = pygame.Rect(menu.x, menu.y + index * 34, menu.width, 34)
            self._dropdown_options[option] = rect
            if option == self.vehicle_type:
                pygame.draw.rect(surf, (43, 65, 92), rect)
            surf.blit(self.font_body.render(option, True, TEXT), (rect.x + 16, rect.y + 9))

    def _draw_scrollbar(self, surf: pygame.Surface) -> None:
        if self._max_scroll() <= 0:
            return
        track = pygame.Rect(self._panel_rect.right - 6, self._panel_rect.y + 4, 3, self._panel_rect.height - 8)
        pygame.draw.rect(surf, (43, 57, 76), track, border_radius=2)
        thumb_h = max(42, int(track.height * self._panel_rect.height / self.CONTENT_HEIGHT))
        travel = track.height - thumb_h
        thumb_y = track.y + int(travel * self.scroll_y / self._max_scroll())
        pygame.draw.rect(surf, (104, 126, 154), (track.x, thumb_y, track.width, thumb_h), border_radius=2)

    def _button(self, surf: pygame.Surface, rect: pygame.Rect, label: str) -> None:
        pygame.draw.rect(surf, WHITE, rect, border_radius=7)
        img = self.font_button.render(label, True, (12, 22, 36))
        surf.blit(
            img,
            (rect.centerx - img.get_width() // 2, rect.centery - img.get_height() // 2),
        )

    def _badge(self, surf: pygame.Surface, label: str, x: int, y: int, width: int = 31) -> None:
        rect = pygame.Rect(x, y, width, 24)
        pygame.draw.rect(surf, WHITE, rect, border_radius=8)
        img = self.font_small.render(label, True, (12, 22, 36))
        surf.blit(img, (rect.centerx - img.get_width() // 2, rect.centery - img.get_height() // 2))

    def _slider(self, surf: pygame.Surface, rect: pygame.Rect, ratio: float) -> None:
        ratio = max(0.0, min(1.0, ratio))
        pygame.draw.rect(surf, (225, 230, 240), rect, border_radius=5)
        filled = rect.copy()
        filled.width = max(4, int(rect.width * ratio))
        pygame.draw.rect(surf, (7, 15, 28), filled, border_radius=5)
        knob_x = rect.x + int(rect.width * ratio)
        pygame.draw.circle(surf, WHITE, (knob_x, rect.centery), 8)
        pygame.draw.circle(surf, (8, 17, 30), (knob_x, rect.centery), 8, 1)

    def _legend_dot(self, surf: pygame.Surface, color: Color, label: str, x: int, y: int) -> None:
        pygame.draw.circle(surf, color, (x + 6, y + 6), 6)
        surf.blit(self.font_small.render(label, True, MUTED), (x + 15, y))

    @staticmethod
    def _dashed_rect(surf: pygame.Surface, rect: pygame.Rect, color: Color) -> None:
        dash = 8
        for x in range(rect.left + 5, rect.right - 5, dash * 2):
            pygame.draw.line(surf, color, (x, rect.top), (min(x + dash, rect.right - 5), rect.top), 2)
            pygame.draw.line(surf, color, (x, rect.bottom), (min(x + dash, rect.right - 5), rect.bottom), 2)
        for y in range(rect.top + 5, rect.bottom - 5, dash * 2):
            pygame.draw.line(surf, color, (rect.left, y), (rect.left, min(y + dash, rect.bottom - 5)), 2)
            pygame.draw.line(surf, color, (rect.right, y), (rect.right, min(y + dash, rect.bottom - 5)), 2)
