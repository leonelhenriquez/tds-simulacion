"""
map_generator.py  —  v5  (pure map generator, no traffic lights)
================================================================
Procedural urban grid map generator for traffic simulation.
Flat-design tiles (residential, park, hospital, river, building).
All random data pre-computed in generate() → zero flicker.
Traffic lights, vehicles, and other simulation modules are designed
to be integrated separately via get_road_segments() / get_intersections().
Demo:  python map_generator.py
"""
import pygame
import random
import math
import sys
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
# ══════════════════════════════════════════════
#  DATA TYPES
# ══════════════════════════════════════════════
@dataclass
class RoadSegment:
    """A road segment between two intersections."""
    start:      Tuple[float, float]
    end:        Tuple[float, float]
    direction:  str                    # 'horizontal' | 'vertical'
    lane_left:  Tuple[float, float]
    lane_right: Tuple[float, float]
    max_speed:  float = 40.0
    name:       str   = ""
@dataclass
class Intersection:
    """A road crossing point."""
    cx:                 float
    cy:                 float
    col:                int
    row:                int
    connected_segments: List[int] = field(default_factory=list)
@dataclass
class TileData:
    """A city block / manzana."""
    col:       int
    row:       int
    x:         float
    y:         float
    w:         float
    h:         float
    tile_type: str
    label:     str  = ""
    elements:  list = field(default_factory=list)   # pre-baked visuals
@dataclass
class SignData:
    """A traffic sign (STOP or speed limit)."""
    kind:  str      # 'stop' | 'speed'
    x:     float
    y:     float
    value: int = 0  # speed value when kind == 'speed'
@dataclass
class MapData:
    """All generated map data."""
    tiles:         List[TileData]
    intersections: List[Intersection]
    road_segments: List[RoadSegment]
    signs:         List[SignData]
    total_width:   int
    total_height:  int
# ══════════════════════════════════════════════
#  PALETTE  (flat design, matches reference)
# ══════════════════════════════════════════════
C_BG            = ( 48,  52,  56)
C_ROAD          = ( 55,  60,  65)
C_INTER         = ( 48,  52,  56)
C_YELLOW        = (230, 190,  40)
C_DASH_WHITE    = (200, 200, 200)
C_GRASS         = (108, 196,  80)
C_TREE_DARK     = ( 34, 120,  40)
C_TREE_MID      = ( 46, 150,  50)
C_TREE_LIGHT    = ( 60, 170,  62)
C_TREE_SHADOW   = ( 28, 100,  34)
C_HOUSE_BODY    = (218, 130,  40)
C_HOUSE_ROOF    = (140,  72,  18)
C_HOUSE_DOOR    = ( 90,  50,  10)
C_WINDOW        = (180, 220, 255)
C_HOSP_WALL     = (160, 165, 175)
C_HOSP_CROSS    = (210,  20,  20)
C_RIVER         = ( 70, 170, 230)
C_RIVER_LIGHT   = (110, 200, 245)
C_BUILD_WALL    = (120, 125, 135)
C_BUILD_WIN     = (170, 205, 235)
C_STOP_RED      = (210,  25,  25)
C_SPEED_RING    = (210,  25,  25)
C_WHITE         = (255, 255, 255)
C_BLACK         = (  0,   0,   0)
C_LABEL_BG      = (  0,   0,   0, 120)
C_PANEL_BG      = ( 22,  24,  28, 190)
C_BTN_PLAY      = ( 50, 190,  90)
C_BTN_RESET     = (200,  65,  45)
C_DOT_GREEN     = ( 46, 160,  50)
# ══════════════════════════════════════════════
#  CONTENT LISTS
# ══════════════════════════════════════════════
STREET_NAMES_H = [
    "Calle Arce", "Paseo General Escalon", "Alameda Juan Pablo II",
    "Carretera Panamericana", "Bulevar de Los Héroes",
    "Av. Independencia", "Calle Delgado", "Blvd. Universitario",
]
STREET_NAMES_V = [
    "Av. Masferrer", "Alameda Juan Pablo II", "Bulevar de los Heroes",
    "Av. España", "Av. Cuscatlán", "Calle Los Sisimiles",
    "Blvd. del Ejército", "Av. Roosevelt",
]
PARK_NAMES  = ["Parque Cuscatlan", "Parque Bicentenario", "Parque Libertad",
               "Parque Infantil", "Parque Central", "Parque San José"]
RIVER_NAMES = ["Rio Lempa", "Rio Acelhuate", "Rio Sucio", "Rio Grande"]
TILE_TYPES   = ["residential", "park", "hospital", "river", "building"]
TILE_WEIGHTS = [0.28, 0.22, 0.10, 0.10, 0.30]
# ══════════════════════════════════════════════
#  DRAWING PRIMITIVES
# ══════════════════════════════════════════════
def _dashed_line(surf, color, p1, p2, dash=14, gap=9, w=2):
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    L = math.hypot(dx, dy)
    if L < 1:
        return
    ux, uy = dx / L, dy / L
    pos, on = 0.0, True
    while pos < L:
        seg = dash if on else gap
        if on:
            x1 = p1[0] + ux * pos
            y1 = p1[1] + uy * pos
            x2 = p1[0] + ux * min(pos + seg, L)
            y2 = p1[1] + uy * min(pos + seg, L)
            pygame.draw.line(surf, color,
                             (int(x1), int(y1)), (int(x2), int(y2)), w)
        pos += seg
        on = not on
def _draw_tree(surf, cx, cy, r):
    """Flat cartoon tree: shadow + dark circle + highlights."""
    pygame.draw.ellipse(surf, C_TREE_SHADOW,
                        (int(cx - r * 0.8), int(cy + r * 0.1),
                         int(r * 1.6), int(r * 0.7)))
    pygame.draw.circle(surf, C_TREE_DARK, (int(cx), int(cy)), int(r))
    pygame.draw.circle(surf, C_TREE_MID,
                       (int(cx - r * 0.25), int(cy - r * 0.25)),
                       int(r * 0.55))
    pygame.draw.circle(surf, C_TREE_LIGHT,
                       (int(cx - r * 0.3), int(cy - r * 0.4)),
                       int(r * 0.25))
def _draw_label(surf, font, text, tx, ty, max_w):
    txt = font.render(text, True, C_WHITE)
    tw = min(txt.get_width(), max_w - 8)
    th = txt.get_height()
    bg = pygame.Surface((tw + 8, th + 4), pygame.SRCALPHA)
    bg.fill(C_LABEL_BG)
    surf.blit(bg, (tx, ty))
    surf.blit(txt, (tx + 4, ty + 2))
def _draw_stop_badge(surf, font, cx, cy):
    w, h = 40, 18
    r = pygame.Rect(int(cx - w // 2), int(cy - h // 2), w, h)
    pygame.draw.rect(surf, C_STOP_RED, r, border_radius=3)
    pygame.draw.rect(surf, C_WHITE, r, 1, border_radius=3)
    txt = font.render("STOP", True, C_WHITE)
    surf.blit(txt, (r.x + (w - txt.get_width()) // 2,
                    r.y + (h - txt.get_height()) // 2))
def _draw_speed_sign(surf, font, cx, cy, speed, radius=16):
    pygame.draw.circle(surf, C_WHITE, (int(cx), int(cy)), radius)
    pygame.draw.circle(surf, C_SPEED_RING, (int(cx), int(cy)), radius, 3)
    txt = font.render(str(speed), True, C_BLACK)
    surf.blit(txt, (int(cx - txt.get_width() // 2),
                    int(cy - txt.get_height() // 2)))
# ══════════════════════════════════════════════
#  TILE RENDERERS
# ══════════════════════════════════════════════
def _render_tile_park(surf, tile, font_label):
    tx, ty, tw, th = int(tile.x), int(tile.y), int(tile.w), int(tile.h)
    pygame.draw.rect(surf, C_GRASS, (tx, ty, tw, th))
    for (cx, cy, r) in tile.elements:
        _draw_tree(surf, tx + cx, ty + cy, r)
    _draw_label(surf, font_label, tile.label, tx + 6, ty + 6, tw)
def _render_tile_residential(surf, tile, font_label):
    tx, ty, tw, th = int(tile.x), int(tile.y), int(tile.w), int(tile.h)
    pygame.draw.rect(surf, C_GRASS, (tx, ty, tw, th))
    hw = int(tw * 0.45)
    hh = int(th * 0.50)
    hx = tx + (tw - hw) // 2
    hy = ty + (th - hh) // 2 + th // 10
    body_h = int(hh * 0.62)
    roof_h = hh - body_h
    pygame.draw.rect(surf, C_HOUSE_BODY, (hx, hy + roof_h, hw, body_h))
    pygame.draw.polygon(surf, C_HOUSE_ROOF, [
        (hx - 4, hy + roof_h), (hx + hw // 2, hy), (hx + hw + 4, hy + roof_h)])
    dw, dh = max(8, hw // 5), max(12, body_h // 2)
    pygame.draw.rect(surf, C_HOUSE_DOOR,
                     (hx + hw // 2 - dw // 2, hy + roof_h + body_h - dh, dw, dh))
    wsize = max(6, hw // 6)
    for wx in [hx + hw // 5, hx + 3 * hw // 5]:
        if wx + wsize < hx + hw:
            pygame.draw.rect(surf, C_WINDOW,
                             (wx, hy + roof_h + body_h // 5, wsize, wsize))
            pygame.draw.rect(surf, C_HOUSE_BODY,
                             (wx, hy + roof_h + body_h // 5, wsize, wsize), 1)
    for (cx, cy, r) in tile.elements:
        _draw_tree(surf, tx + cx, ty + cy, r)
def _render_tile_hospital(surf, tile, font_label):
    tx, ty, tw, th = int(tile.x), int(tile.y), int(tile.w), int(tile.h)
    pygame.draw.rect(surf, C_GRASS, (tx, ty, tw, th))
    bw, bh = tw // 2, th // 2
    bx = tx + (tw - bw) // 2
    by = ty + (th - bh) // 2
    pygame.draw.rect(surf, C_HOSP_WALL, (bx, by, bw, bh))
    pygame.draw.rect(surf, (100, 105, 115), (bx, by, bw, bh), 2)
    ws = max(5, bw // 6)
    for r_ in range(2):
        for c_ in range(2):
            wx = bx + 5 + c_ * (bw - 10) // 2
            wy = by + 5 + r_ * (bh - 10) // 2
            pygame.draw.rect(surf, C_BUILD_WIN, (wx, wy, ws, ws))
    cx, cy = bx + bw // 2, by + bh // 2
    arm = max(5, bw // 5)
    thick = max(3, arm // 2)
    pygame.draw.rect(surf, C_HOSP_CROSS,
                     (cx - thick // 2, cy - arm, thick, arm * 2))
    pygame.draw.rect(surf, C_HOSP_CROSS,
                     (cx - arm, cy - thick // 2, arm * 2, thick))
    _draw_label(surf, font_label, "Hospital", tx + 6, by + bh + 4, tw)
def _render_tile_river(surf, tile, font_label):
    tx, ty, tw, th = int(tile.x), int(tile.y), int(tile.w), int(tile.h)
    pygame.draw.rect(surf, C_GRASS, (tx, ty, tw, th))
    river_elems = [e for e in tile.elements if e[0] == "river"]
    tree_elems  = [e for e in tile.elements if e[0] == "tree"]
    for (_, cx, cy, r) in river_elems:
        pygame.draw.circle(surf, C_RIVER, (tx + int(cx), ty + int(cy)), int(r))
    if river_elems:
        first = river_elems[0]
        pygame.draw.circle(surf, C_RIVER_LIGHT,
                           (tx + int(first[1] - first[3] * 0.3),
                            ty + int(first[2] - first[3] * 0.3)),
                           int(first[3] * 0.3))
    for (_, cx, cy, r) in tree_elems:
        _draw_tree(surf, tx + int(cx), ty + int(cy), int(r))
    _draw_label(surf, font_label, tile.label, tx + 6, ty + 6, tw)
def _render_tile_building(surf, tile, font_label):
    tx, ty, tw, th = int(tile.x), int(tile.y), int(tile.w), int(tile.h)
    pygame.draw.rect(surf, C_GRASS, (tx, ty, tw, th))
    m = max(12, min(tw, th) // 7)
    bx, by, bw, bh = tx + m, ty + m, tw - 2 * m, th - 2 * m
    pygame.draw.rect(surf, C_BUILD_WALL, (bx, by, bw, bh))
    pygame.draw.rect(surf, (80, 85, 95), (bx, by, bw, bh), 2)
    cols_w = max(2, bw // 22)
    rows_w = max(2, bh // 22)
    ws = max(5, min(bw // (cols_w + 1), bh // (rows_w + 1)) - 3)
    for r_ in range(rows_w):
        for c_ in range(cols_w):
            wx = bx + 5 + c_ * (bw - 10) // cols_w
            wy = by + 5 + r_ * (bh - 10) // rows_w
            pygame.draw.rect(surf, C_BUILD_WIN, (wx, wy, ws, ws))
            pygame.draw.rect(surf, (140, 155, 175), (wx, wy, ws, ws), 1)
    for (cx, cy, r) in tile.elements:
        pygame.draw.circle(surf, C_DOT_GREEN,
                           (tx + int(cx), ty + int(cy)), int(r))
# ══════════════════════════════════════════════
#  MAP GENERATOR
# ══════════════════════════════════════════════
class MapGenerator:
    """
    Procedural urban grid map generator for traffic simulation.
    This class generates the MAP ONLY. Traffic lights, vehicles,
    and other simulation logic are separate modules that integrate
    via get_road_segments() and get_intersections().
    """
    def __init__(self, cols: int = 4, rows: int = 3,
                 block_size: int = 160, road_width: int = 65):
        self.cols       = max(2, cols)
        self.rows       = max(2, rows)
        self.block_size = block_size
        self.road_width = road_width
        self.total_width  = cols * block_size + (cols + 1) * road_width
        self.total_height = rows * block_size + (rows + 1) * road_width
        self._map_data: Optional[MapData] = None
        # Fonts (lazy)
        self._f_street: Optional[pygame.font.Font] = None
        self._f_sign:   Optional[pygame.font.Font] = None
        self._f_panel:  Optional[pygame.font.Font] = None
        self._f_btn:    Optional[pygame.font.Font] = None
        self._f_label:  Optional[pygame.font.Font] = None
    # ── helpers ─────────────────────────────────────────────────────────
    def _inter_center(self, col, row):
        cx = col * (self.block_size + self.road_width) + self.road_width / 2
        cy = row * (self.block_size + self.road_width) + self.road_width / 2
        return cx, cy
    def _tile_rect(self, col, row):
        x = col * (self.block_size + self.road_width) + self.road_width
        y = row * (self.block_size + self.road_width) + self.road_width
        return x, y, self.block_size, self.block_size
    def _init_fonts(self):
        if self._f_street is not None:
            return
        rw = self.road_width
        self._f_street = pygame.font.SysFont("arial", max(11, rw // 5), bold=True)
        self._f_sign   = pygame.font.SysFont("arial", max(8,  rw // 7), bold=True)
        self._f_panel  = pygame.font.SysFont("arial", max(14, rw // 4))
        self._f_btn    = pygame.font.SysFont("arial", max(15, rw // 3), bold=True)
        self._f_label  = pygame.font.SysFont("arial", max(10, rw // 5), bold=True)
    # ── GENERATE ────────────────────────────────────────────────────────
    def generate(self) -> MapData:
        rng = random.Random()
        rw  = self.road_width
        # Street names
        h_pool = list(STREET_NAMES_H); rng.shuffle(h_pool)
        v_pool = list(STREET_NAMES_V); rng.shuffle(v_pool)
        h_names = [h_pool[i % len(h_pool)] for i in range(self.rows + 1)]
        v_names = [v_pool[i % len(v_pool)] for i in range(self.cols + 1)]
        park_pool  = list(PARK_NAMES);  rng.shuffle(park_pool)
        river_pool = list(RIVER_NAMES); rng.shuffle(river_pool)
        park_idx = river_idx = 0
        # ── Tiles ──
        tiles: List[TileData] = []
        for row in range(self.rows):
            for col in range(self.cols):
                x, y, w, h = self._tile_rect(col, row)
                ttype = rng.choices(TILE_TYPES, weights=TILE_WEIGHTS, k=1)[0]
                label = ""
                elements = []
                if ttype == "park":
                    label = park_pool[park_idx % len(park_pool)]; park_idx += 1
                    margin = max(16, min(w, h) // 5)
                    for _ in range(rng.randint(4, 7)):
                        elements.append((rng.randint(margin, w - margin),
                                         rng.randint(margin, h - margin),
                                         rng.randint(max(10, w // 10),
                                                     max(14, w // 6))))
                elif ttype == "river":
                    label = river_pool[river_idx % len(river_pool)]; river_idx += 1
                    rcx = w // 2 + rng.randint(-w // 8, w // 8)
                    rcy = h // 2 + rng.randint(-h // 8, h // 8)
                    main_r = max(w // 4, h // 4)
                    elements.append(("river", rcx, rcy, main_r))
                    for _ in range(rng.randint(6, 10)):
                        angle = rng.uniform(0, 2 * math.pi)
                        dist  = rng.uniform(main_r * 0.3, main_r * 1.2)
                        elements.append(("river",
                                         rcx + int(dist * math.cos(angle)),
                                         rcy + int(dist * math.sin(angle)),
                                         rng.randint(main_r // 3, main_r)))
                    for _ in range(rng.randint(2, 5)):
                        tx_ = rng.randint(8, w - 8)
                        ty_ = rng.randint(8, h - 8)
                        if math.hypot(tx_ - rcx, ty_ - rcy) > main_r * 1.2:
                            elements.append(("tree", tx_, ty_,
                                             rng.randint(max(8, w // 12),
                                                         max(10, w // 8))))
                elif ttype == "residential":
                    hw_ = int(w * 0.45); hh_ = int(h * 0.50)
                    hx_ = (w - hw_) // 2; hy_ = (h - hh_) // 2 + h // 10
                    for _ in range(rng.randint(1, 3)):
                        ax, ay = rng.randint(6, w - 6), rng.randint(6, h - 6)
                        if (abs(ax - (hx_ + hw_ // 2)) > hw_ // 2 + 12 or
                                abs(ay - (hy_ + hh_ // 2)) > hh_ // 2 + 12):
                            elements.append((ax, ay,
                                             rng.randint(max(6, w // 14),
                                                         max(8, w // 10))))
                elif ttype == "building":
                    m = max(12, min(w, h) // 7)
                    for _ in range(rng.randint(2, 5)):
                        dx_, dy_ = rng.randint(4, w - 4), rng.randint(4, h - 4)
                        if dx_ < m - 4 or dx_ > w - m + 4 or dy_ < m - 4 or dy_ > h - m + 4:
                            elements.append((dx_, dy_, rng.randint(3, 6)))
                tiles.append(TileData(col, row, x, y, w, h, ttype, label, elements))
        # ── Intersections (no traffic lights) ──
        intersections: List[Intersection] = []
        for row_ in range(self.rows + 1):
            for col_ in range(self.cols + 1):
                cx, cy = self._inter_center(col_, row_)
                intersections.append(Intersection(cx, cy, col_, row_))
        # ── Road segments ──
        road_segments: List[RoadSegment] = []
        quarter = rw / 4
        for row_ in range(self.rows + 1):
            for col_ in range(self.cols):
                il = intersections[row_ * (self.cols + 1) + col_]
                ir = intersections[row_ * (self.cols + 1) + col_ + 1]
                seg = RoadSegment(
                    start=(il.cx, il.cy), end=(ir.cx, ir.cy),
                    direction="horizontal",
                    lane_left=(il.cx, il.cy - quarter),
                    lane_right=(il.cx, il.cy + quarter),
                    max_speed=40.0, name=h_names[row_])
                road_segments.append(seg)
                il.connected_segments.append(len(road_segments) - 1)
                ir.connected_segments.append(len(road_segments) - 1)
        for col_ in range(self.cols + 1):
            for row_ in range(self.rows):
                it = intersections[row_       * (self.cols + 1) + col_]
                ib = intersections[(row_ + 1) * (self.cols + 1) + col_]
                seg = RoadSegment(
                    start=(it.cx, it.cy), end=(ib.cx, ib.cy),
                    direction="vertical",
                    lane_left=(it.cx - quarter, it.cy),
                    lane_right=(it.cx + quarter, it.cy),
                    max_speed=40.0, name=v_names[col_])
                road_segments.append(seg)
                it.connected_segments.append(len(road_segments) - 1)
                ib.connected_segments.append(len(road_segments) - 1)
        # ── Signs ──
        signs: List[SignData] = []
        for inter in intersections:
            if rng.random() < 0.25:
                offset = rw * 0.35
                sx = inter.cx + rng.choice([-offset, offset])
                sy = inter.cy - offset
                signs.append(SignData("stop", sx, sy))
        for seg in road_segments:
            if seg.direction == "horizontal" and rng.random() < 0.30:
                mx = (seg.start[0] + seg.end[0]) / 2
                my = seg.start[1] + quarter + 4
                signs.append(SignData("speed", mx, my, rng.choice([30, 40])))
        self._map_data = MapData(
            tiles=tiles, intersections=intersections,
            road_segments=road_segments, signs=signs,
            total_width=self.total_width, total_height=self.total_height)
        return self._map_data
    # ── DRAW ────────────────────────────────────────────────────────────
    def draw(self, surface: pygame.Surface, offset_x: int = 0, offset_y: int = 0):
        if self._map_data is None:
            self.generate()
        self._init_fonts()
        data = self._map_data
        rw   = self.road_width
        ox, oy = offset_x, offset_y
        # 1 ── Background (asphalt)
        surface.fill(C_BG)
        # 2 ── Tiles
        for tile in data.tiles:
            t = TileData(tile.col, tile.row,
                         tile.x + ox, tile.y + oy,
                         tile.w, tile.h,
                         tile.tile_type, tile.label, tile.elements)
            renderer = {
                "park":        _render_tile_park,
                "residential": _render_tile_residential,
                "hospital":    _render_tile_hospital,
                "river":       _render_tile_river,
                "building":    _render_tile_building,
            }.get(t.tile_type)
            if renderer:
                renderer(surface, t, self._f_label)
        # 3 ── Intersection zones (darker squares)
        for inter in data.intersections:
            ix = int(inter.cx - rw // 2 + ox)
            iy = int(inter.cy - rw // 2 + oy)
            pygame.draw.rect(surface, C_INTER, (ix, iy, rw, rw))
        # 4 ── Road markings
        ht = rw // 2
        for seg in data.road_segments:
            x0, y0 = seg.start[0] + ox, seg.start[1] + oy
            x1, y1 = seg.end[0]   + ox, seg.end[1]   + oy
            if seg.direction == "horizontal":
                # White dashed lane edges
                for dy_ in (-ht + 2, ht - 2):
                    _dashed_line(surface, C_DASH_WHITE,
                                 (int(x0), int(y0 + dy_)),
                                 (int(x1), int(y1 + dy_)),
                                 dash=18, gap=12, w=2)
                # Double yellow center line
                pygame.draw.line(surface, C_YELLOW,
                                 (int(x0), int(y0 - 2)),
                                 (int(x1), int(y1 - 2)), 2)
                pygame.draw.line(surface, C_YELLOW,
                                 (int(x0), int(y0 + 2)),
                                 (int(x1), int(y1 + 2)), 2)
                # Street name
                mid_x = (x0 + x1) / 2
                txt = self._f_street.render(seg.name, True, C_WHITE)
                surface.blit(txt, (int(mid_x - txt.get_width() // 2),
                                   int(y0 - txt.get_height() // 2)))
            else:  # vertical
                for dx_ in (-ht + 2, ht - 2):
                    _dashed_line(surface, C_DASH_WHITE,
                                 (int(x0 + dx_), int(y0)),
                                 (int(x1 + dx_), int(y1)),
                                 dash=18, gap=12, w=2)
                pygame.draw.line(surface, C_YELLOW,
                                 (int(x0 - 2), int(y0)),
                                 (int(x1 - 2), int(y1)), 2)
                pygame.draw.line(surface, C_YELLOW,
                                 (int(x0 + 2), int(y0)),
                                 (int(x1 + 2), int(y1)), 2)
                mid_y = (y0 + y1) / 2
                txt     = self._f_street.render(seg.name, True, C_WHITE)
                txt_rot = pygame.transform.rotate(txt, 90)
                surface.blit(txt_rot,
                             (int(x0 - txt_rot.get_width() // 2),
                              int(mid_y - txt_rot.get_height() // 2)))
        # 5 ── Signs
        for sign in data.signs:
            sx, sy = sign.x + ox, sign.y + oy
            if sign.kind == "stop":
                _draw_stop_badge(surface, self._f_sign, int(sx), int(sy))
            elif sign.kind == "speed":
                _draw_speed_sign(surface, self._f_sign, int(sx), int(sy),
                                 sign.value, radius=max(10, rw // 6))
    # ── HUD ──────────────────────────────────────────────────────────────
    def draw_stats_panel(self, surface: pygame.Surface,
                         vehicle_count: int = 0, status: str = "Playing"):
        if self._map_data is None:
            return
        self._init_fonts()
        data = self._map_data
        pw, ph = 260, 120
        px, py = 10, surface.get_height() - ph - 10
        bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
        bg.fill(C_PANEL_BG)
        surface.blit(bg, (px, py))
        pygame.draw.rect(surface, (70, 75, 90), (px, py, pw, ph), 2,
                         border_radius=6)
        sc = (80, 230, 100) if status == "Playing" else (230, 160, 50)
        lines = [
            (f"Vehiculos: {vehicle_count}",                              C_WHITE),
            (f"Avenidas: {len(set(s.name for s in data.road_segments))}",C_WHITE),
            (f"Intersecciones principales: {len(data.intersections)}",   C_WHITE),
            (f"Status: {status}",                                        sc),
        ]
        lh = (ph - 14) // len(lines)
        for i, (text, col) in enumerate(lines):
            txt = self._f_panel.render(text, True, col)
            surface.blit(txt, (px + 10, py + 8 + i * lh))
    def draw_ui_buttons(self, surface) -> Tuple[pygame.Rect, pygame.Rect]:
        self._init_fonts()
        bw, bh, pad = 100, 38, 10
        play_r  = pygame.Rect(pad, pad, bw, bh)
        reset_r = pygame.Rect(pad + bw + pad, pad, bw, bh)
        for rect, color, label in [
            (play_r,  C_BTN_PLAY,  "▶  Play"),
            (reset_r, C_BTN_RESET, "↺  Reset"),
        ]:
            pygame.draw.rect(surface, color, rect, border_radius=8)
            pygame.draw.rect(surface, C_WHITE, rect, 2, border_radius=8)
            txt = self._f_btn.render(label, True, C_WHITE)
            surface.blit(txt, (rect.x + (bw - txt.get_width()) // 2,
                               rect.y + (bh - txt.get_height()) // 2))
        return play_r, reset_r
    # ── Public API ───────────────────────────────────────────────────────
    def get_road_segments(self) -> List[RoadSegment]:
        if self._map_data is None:
            self.generate()
        return self._map_data.road_segments
    def get_intersections(self) -> List[Intersection]:
        if self._map_data is None:
            self.generate()
        return self._map_data.intersections
    def get_tiles(self) -> List[TileData]:
        if self._map_data is None:
            self.generate()
        return self._map_data.tiles
    def get_signs(self) -> List[SignData]:
        if self._map_data is None:
            self.generate()
        return self._map_data.signs
    def reset(self):
        """Regenerate the map with the same parameters."""
        self.generate()
# ══════════════════════════════════════════════
#  DEMO
# ══════════════════════════════════════════════
def main():
    pygame.init()
    pygame.display.set_caption("Simulador de Tráfico — Generador de Mapa")
    COLS, ROWS   = 4, 3
    BLOCK_SIZE   = 160
    ROAD_WIDTH   = 65
    gen = MapGenerator(cols=COLS, rows=ROWS,
                       block_size=BLOCK_SIZE, road_width=ROAD_WIDTH)
    gen.generate()
    # Create a resizable window
    screen = pygame.display.set_mode((gen.total_width, gen.total_height), pygame.RESIZABLE)
    clock  = pygame.time.Clock()
    is_playing = True
    logical_size = (gen.total_width, gen.total_height)
    map_surf = pygame.Surface(logical_size)
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                # Handle window resize
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    is_playing = not is_playing
                elif event.key == pygame.K_r:
                    gen.reset()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # Map screen coordinates back to logical coordinates for UI clicks
                sw, sh = screen.get_size()
                lx = event.pos[0] * (logical_size[0] / sw)
                ly = event.pos[1] * (logical_size[1] / sh)
                
                pr, rr = gen.draw_ui_buttons(map_surf)
                if pr.collidepoint((lx, ly)):
                    is_playing = not is_playing
                elif rr.collidepoint((lx, ly)):
                    gen.reset()

        # Draw everything to the logical surface
        gen.draw(map_surf)
        gen.draw_stats_panel(map_surf, vehicle_count=0,
                             status="Playing" if is_playing else "Paused")

        gen.draw_ui_buttons(map_surf)
        
        # Scale logical surface to current window size
        scaled_surf = pygame.transform.smoothscale(map_surf, screen.get_size())
        screen.blit(scaled_surf, (0, 0))
        
        pygame.display.flip()
        clock.tick(60)
    pygame.quit()
    sys.exit()
if __name__ == "__main__":
    main()