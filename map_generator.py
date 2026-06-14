"""
map_generator.py  -  v8  (interactive road grid model)
==============================================================================
Procedural urban grid map generator for traffic simulation.

Visual style: pixel-art intersection look (dark asphalt, gray sidewalks,
double yellow center lines, white solid edge lines, dashed lane dividers,
zebra crosswalks at intersections, dense green vegetation blocks).

Layout: NxM grid of city blocks. Streets are placed between blocks, like the
reference image, and reach the screen edges so other modules can spawn traffic
on top of this road model.

Each street has two lanes per direction. The dashed white lines mark the split
between the inner and outer lane on each side of the double yellow divider.

Edge exits: streets extend to the screen border so vehicles can
disappear off one side and reappear on the opposite side.

Public API:
  generate()            → MapData
  draw(surface)         → renders the current map model
  get_road_segments()   → List[RoadSegment]
  get_intersections()   → List[Intersection]
  get_spawn_points()    → List[SpawnPoint]  (for vehicle wrapping)
  get_tiles()           → List[TileData]
  reset()               → regenerate

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
    lanes_left:  List[Tuple[float, float]] = field(default_factory=list)
    lanes_right: List[Tuple[float, float]] = field(default_factory=list)
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
    elements:  list = field(default_factory=list)

@dataclass
class SpawnPoint:
    """
    A vehicle spawn/despawn point at the screen edge.
    Vehicles spawn at (spawn_x, spawn_y) and move in `direction`.
    When they exit at (exit_x, exit_y) they reappear at the opposite spawn.
    """
    direction:  str    # 'right' | 'left' | 'up' | 'down'
    lane:       int    # lane index (0 = inner, 1 = outer)
    lane_y:     float  # y-coordinate for horizontal lanes
    lane_x:     float  # x-coordinate for vertical lanes
    spawn_x:    float
    spawn_y:    float
    exit_x:     float
    exit_y:     float

@dataclass
class MapData:
    """All generated map data."""
    tiles:         List[TileData]
    intersections: List[Intersection]
    road_segments: List[RoadSegment]
    spawn_points:  List[SpawnPoint]
    total_width:   int
    total_height:  int

# ══════════════════════════════════════════════
#  PALETTE  — pixel-art intersection style
# ══════════════════════════════════════════════
# Asphalt
C_ASPHALT        = ( 42,  44,  46)   # very dark grey, main road surface
C_ASPHALT_STRIPE = ( 38,  40,  42)   # slightly darker for texture stripes
C_INTER          = ( 36,  38,  40)   # intersection box (darkest)
# Road markings
C_YELLOW         = (255, 200,   0)   # vivid double yellow center line
C_WHITE          = (255, 255, 255)   # lane dividers + edge lines + crosswalk
C_DASH           = (210, 210, 210)   # dashed lane divider (slightly off-white)
# Sidewalk / curb
C_SIDEWALK       = ( 96,  96, 100)   # grey cement sidewalk strip
C_CURB           = ( 70,  72,  76)   # darker curb edge
# Vegetation (pixel-art dark greens)
C_GRASS          = ( 68, 148,  52)   # grass base
C_TREE_DARK      = ( 28,  98,  32)   # tree shadow / base
C_TREE_MID       = ( 44, 128,  40)   # tree mid-tone
C_TREE_LIGHT     = ( 72, 160,  56)   # tree highlight
C_TREE_SHADOW    = ( 20,  72,  24)   # shadow ellipse
# Block tile elements
C_HOUSE_BODY     = (218, 130,  40)
C_HOUSE_ROOF     = (140,  72,  18)
C_HOUSE_DOOR     = ( 90,  50,  10)
C_WINDOW         = (180, 220, 255)
C_HOSP_WALL      = (160, 165, 175)
C_HOSP_CROSS     = (210,  20,  20)
C_RIVER          = ( 70, 170, 230)
C_RIVER_LIGHT    = (110, 200, 245)
C_BUILD_WALL     = (110, 115, 125)
C_BUILD_WIN      = (160, 195, 225)
C_DOT_GREEN      = ( 46, 160,  50)
# UI
C_LABEL_BG       = (  0,   0,   0, 120)

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
    """Pixel-art style tree: shadow + dark circle + highlights."""
    pygame.draw.ellipse(surf, C_TREE_SHADOW,
                        (int(cx - r * 0.8), int(cy + r * 0.2),
                         int(r * 1.6), int(r * 0.6)))
    pygame.draw.circle(surf, C_TREE_DARK, (int(cx), int(cy)), int(r))
    pygame.draw.circle(surf, C_TREE_MID,
                       (int(cx - r * 0.22), int(cy - r * 0.22)),
                       int(r * 0.58))
    pygame.draw.circle(surf, C_TREE_LIGHT,
                       (int(cx - r * 0.32), int(cy - r * 0.38)),
                       int(r * 0.26))

def _draw_label(surf, font, text, tx, ty, max_w):
    txt = font.render(text, True, C_WHITE)
    tw = min(txt.get_width(), max_w - 8)
    th = txt.get_height()
    bg = pygame.Surface((tw + 8, th + 4), pygame.SRCALPHA)
    bg.fill(C_LABEL_BG)
    surf.blit(bg, (tx, ty))
    surf.blit(txt, (tx + 4, ty + 2))

def _draw_crosswalk(surf, cx, cy, rw, direction):
    """
    Draw a subtle pedestrian crossing marker at an intersection entry.
    direction: 'top' | 'bottom' | 'left' | 'right' (which side of the intersection)
    """
    sidewalk = max(6, rw // 8)
    inset = max(5, rw // 16)
    gap = max(6, rw // 14)
    line_w = 2
    color = (218, 218, 218)
    x_start = int(cx - rw // 2 + sidewalk)
    x_end = int(cx + rw // 2 - sidewalk)
    y_start = int(cy - rw // 2 + sidewalk)
    y_end = int(cy + rw // 2 - sidewalk)

    if direction in ('top', 'bottom'):
        line_y = cy - rw // 2 + sidewalk + inset if direction == 'top' else cy + rw // 2 - sidewalk - inset
        for offset in (-gap / 2, gap / 2):
            y = int(line_y + offset)
            pygame.draw.line(surf, color, (x_start, y), (x_end, y), line_w)
    else:
        line_x = cx - rw // 2 + sidewalk + inset if direction == 'left' else cx + rw // 2 - sidewalk - inset
        for offset in (-gap / 2, gap / 2):
            x = int(line_x + offset)
            pygame.draw.line(surf, color, (x, y_start), (x, y_end), line_w)

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
    Procedural urban grid map generator with pixel-art street visuals.

    Street anatomy (per road, centered on intersection grid line):
      ┌─ sidewalk (C_SIDEWALK) ─────────────────────────────┐
      │  solid white edge line                               │
      │  lane (right-going / going-down)                    │
      │  dashed white lane divider                          │
      │  ═══ double yellow center line ═══                  │
      │  dashed white lane divider                          │
      │  lane (left-going / going-up)                       │
      │  solid white edge line                              │
      └─ sidewalk ──────────────────────────────────────────┘

    Intersections: darker box with zebra crosswalks on all 4 entries.
    """
    def __init__(self, cols: int = 4, rows: int = 4,
                 block_size: int = 160, road_width: int = 96):
        self.cols       = max(2, cols)
        self.rows       = max(2, rows)
        self.block_size = block_size
        self.road_width = road_width          # total road width incl. sidewalks
        self.sidewalk_w = max(6, road_width // 9)   # sidewalk strip on each side
        self.total_width  = self.cols * block_size + (self.cols - 1) * road_width
        self.total_height = self.rows * block_size + (self.rows - 1) * road_width
        self._map_data: Optional[MapData] = None
        self._f_street: Optional[pygame.font.Font] = None
        self._f_label:  Optional[pygame.font.Font] = None

    # ── helpers ─────────────────────────────────────────────────────────
    def _road_center_x(self, col):
        return ((col + 1) * self.block_size +
                col * self.road_width + self.road_width / 2)

    def _road_center_y(self, row):
        return ((row + 1) * self.block_size +
                row * self.road_width + self.road_width / 2)

    def _inter_center(self, col, row):
        return self._road_center_x(col), self._road_center_y(row)

    def _lane_offsets(self) -> Tuple[float, float, float]:
        lane_w = (self.road_width - 2 * self.sidewalk_w) / 4
        inner = lane_w / 2
        outer = lane_w * 1.5
        return inner, outer, lane_w

    def _tile_rect(self, col, row):
        x = col * (self.block_size + self.road_width)
        y = row * (self.block_size + self.road_width)
        return x, y, self.block_size, self.block_size

    def _init_fonts(self):
        if self._f_street is not None:
            return
        rw = self.road_width
        self._f_street = pygame.font.SysFont("arial", max(11, rw // 5), bold=True)
        self._f_label  = pygame.font.SysFont("arial", max(10, rw // 5), bold=True)

    # ── GENERATE ────────────────────────────────────────────────────────
    def generate(self) -> MapData:
        rng = random.Random()
        rw  = self.road_width
        lane_inner, lane_outer, _ = self._lane_offsets()

        # Street names
        h_pool = list(STREET_NAMES_H); rng.shuffle(h_pool)
        v_pool = list(STREET_NAMES_V); rng.shuffle(v_pool)
        h_names = [h_pool[i % len(h_pool)] for i in range(self.rows - 1)]
        v_names = [v_pool[i % len(v_pool)] for i in range(self.cols - 1)]
        park_pool  = list(PARK_NAMES);  rng.shuffle(park_pool)
        river_pool = list(RIVER_NAMES); rng.shuffle(river_pool)
        park_idx = river_idx = 0

        # ── Tiles ──────────────────────────────────────────────────────
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
                    for _ in range(rng.randint(5, 9)):
                        elements.append((rng.randint(margin, w - margin),
                                         rng.randint(margin, h - margin),
                                         rng.randint(max(10, w // 10),
                                                     max(16, w // 6))))
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
                    for _ in range(rng.randint(3, 6)):
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

        # ── Intersections ───────────────────────────────────────────────
        intersections: List[Intersection] = []
        for row_ in range(self.rows - 1):
            for col_ in range(self.cols - 1):
                cx, cy = self._inter_center(col_, row_)
                intersections.append(Intersection(cx, cy, col_, row_))

        # ── Road segments ───────────────────────────────────────────────
        road_segments: List[RoadSegment] = []
        inter_cols = self.cols - 1

        # Horizontal streets span edge-to-edge between block rows.
        for row_ in range(self.rows - 1):
            _, cy = self._inter_center(0, row_)
            lanes_left = [(0, cy - lane_inner), (0, cy - lane_outer)]
            lanes_right = [(0, cy + lane_inner), (0, cy + lane_outer)]
            seg = RoadSegment(
                start=(0, cy), end=(self.total_width, cy),
                direction="horizontal",
                lane_left=lanes_left[0],
                lane_right=lanes_right[0],
                lanes_left=lanes_left,
                lanes_right=lanes_right,
                max_speed=40.0, name=h_names[row_])
            road_segments.append(seg)
            seg_idx = len(road_segments) - 1
            for col_ in range(self.cols - 1):
                intersections[row_ * inter_cols + col_].connected_segments.append(seg_idx)

        # Vertical streets span edge-to-edge between block columns.
        for col_ in range(self.cols - 1):
            cx, _ = self._inter_center(col_, 0)
            lanes_left = [(cx - lane_inner, 0), (cx - lane_outer, 0)]
            lanes_right = [(cx + lane_inner, 0), (cx + lane_outer, 0)]
            seg = RoadSegment(
                start=(cx, 0), end=(cx, self.total_height),
                direction="vertical",
                lane_left=lanes_left[0],
                lane_right=lanes_right[0],
                lanes_left=lanes_left,
                lanes_right=lanes_right,
                max_speed=40.0, name=v_names[col_])
            road_segments.append(seg)
            seg_idx = len(road_segments) - 1
            for row_ in range(self.rows - 1):
                intersections[row_ * inter_cols + col_].connected_segments.append(seg_idx)

        # ── Spawn points (edge exits for vehicle wrapping) ──────────────
        # Each internal horizontal street has LEFT and RIGHT spawn points.
        # Each internal vertical street has TOP and BOTTOM spawn points.
        spawn_points: List[SpawnPoint] = []
        W = self.total_width
        H = self.total_height
        MARGIN = 80   # how far outside the screen vehicles are spawned

        for row_ in range(self.rows - 1):
            cx, cy = self._inter_center(0, row_)
            for lane_idx, offset in enumerate((lane_inner, lane_outer)):
                lane_id = row_ * 2 + lane_idx

                # Lanes going RIGHT (lower half of the road).
                ly_right = cy + offset
                spawn_points.append(SpawnPoint(
                    direction="right", lane=lane_id,
                    lane_y=ly_right, lane_x=0,
                    spawn_x=-MARGIN, spawn_y=ly_right,
                    exit_x=W + MARGIN, exit_y=ly_right))

                # Lanes going LEFT (upper half of the road).
                ly_left = cy - offset
                spawn_points.append(SpawnPoint(
                    direction="left", lane=lane_id,
                    lane_y=ly_left, lane_x=W,
                    spawn_x=W + MARGIN, spawn_y=ly_left,
                    exit_x=-MARGIN, exit_y=ly_left))

        for col_ in range(self.cols - 1):
            cx, cy = self._inter_center(col_, 0)
            for lane_idx, offset in enumerate((lane_inner, lane_outer)):
                lane_id = col_ * 2 + lane_idx

                # Lanes going DOWN (right half of the road).
                lx_down = cx + offset
                spawn_points.append(SpawnPoint(
                    direction="down", lane=lane_id,
                    lane_y=0, lane_x=lx_down,
                    spawn_x=lx_down, spawn_y=-MARGIN,
                    exit_x=lx_down, exit_y=H + MARGIN))

                # Lanes going UP (left half of the road).
                lx_up = cx - offset
                spawn_points.append(SpawnPoint(
                    direction="up", lane=lane_id,
                    lane_y=H, lane_x=lx_up,
                    spawn_x=lx_up, spawn_y=H + MARGIN,
                    exit_x=lx_up, exit_y=-MARGIN))

        self._map_data = MapData(
            tiles=tiles, intersections=intersections,
            road_segments=road_segments,
            spawn_points=spawn_points,
            total_width=self.total_width, total_height=self.total_height)
        return self._map_data

    # ── DRAW ────────────────────────────────────────────────────────────
    def draw(self, surface: pygame.Surface, offset_x: int = 0, offset_y: int = 0):
        if self._map_data is None:
            self.generate()
        self._init_fonts()
        data = self._map_data
        rw   = self.road_width
        sw   = self.sidewalk_w
        ox, oy = offset_x, offset_y

        # ── 1. Background — fill everything with asphalt color ──────────
        surface.fill(C_ASPHALT)

        # ── 2. Subtle asphalt texture: horizontal micro-stripes ─────────
        # Draw very thin alternating darker lines every 4px on the entire surface
        surf_w = surface.get_width()
        surf_h = surface.get_height()
        for yy in range(0, surf_h, 4):
            pygame.draw.line(surface, C_ASPHALT_STRIPE, (0, yy), (surf_w, yy), 1)

        # ── 3. Sidewalks alongside every road ───────────────────────────
        # For each internal horizontal road: draw top & bottom sidewalk
        for row_ in range(self.rows - 1):
            _, cy = self._inter_center(0, row_)
            cy += oy
            top_sw_y    = cy - rw // 2
            bottom_sw_y = cy + rw // 2 - sw
            pygame.draw.rect(surface, C_SIDEWALK,
                             (0, int(top_sw_y), surf_w, sw))
            pygame.draw.rect(surface, C_SIDEWALK,
                             (0, int(bottom_sw_y), surf_w, sw))
            # Curb edge lines
            pygame.draw.line(surface, C_CURB,
                             (0, int(top_sw_y + sw)),
                             (surf_w, int(top_sw_y + sw)), 1)
            pygame.draw.line(surface, C_CURB,
                             (0, int(bottom_sw_y)),
                             (surf_w, int(bottom_sw_y)), 1)

        # For each internal vertical road: draw left & right sidewalk
        for col_ in range(self.cols - 1):
            cx, _ = self._inter_center(col_, 0)
            cx += ox
            left_sw_x  = cx - rw // 2
            right_sw_x = cx + rw // 2 - sw
            pygame.draw.rect(surface, C_SIDEWALK,
                             (int(left_sw_x), 0, sw, surf_h))
            pygame.draw.rect(surface, C_SIDEWALK,
                             (int(right_sw_x), 0, sw, surf_h))
            pygame.draw.line(surface, C_CURB,
                             (int(left_sw_x + sw), 0),
                             (int(left_sw_x + sw), surf_h), 1)
            pygame.draw.line(surface, C_CURB,
                             (int(right_sw_x), 0),
                             (int(right_sw_x), surf_h), 1)

        # ── 4. Tiles (city blocks) ──────────────────────────────────────
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

        # ── 5. Road markings per street ─────────────────────────────────
        ht = rw // 2    # half road width
        _, _, lane_w = self._lane_offsets()

        for seg in data.road_segments:
            x0, y0 = seg.start[0] + ox, seg.start[1] + oy
            x1, y1 = seg.end[0]   + ox, seg.end[1]   + oy

            if seg.direction == "horizontal":
                road_top    = y0 - ht + sw      # inner edge of top sidewalk
                road_bottom = y0 + ht - sw      # inner edge of bottom sidewalk

                # Solid white edge lines (just inside sidewalk)
                pygame.draw.line(surface, C_WHITE,
                                 (int(x0), int(road_top)),
                                 (int(x1), int(road_top)), 2)
                pygame.draw.line(surface, C_WHITE,
                                 (int(x0), int(road_bottom)),
                                 (int(x1), int(road_bottom)), 2)

                # Dashed white lane dividers (between edge and center)
                lane_div_top    = y0 - lane_w
                lane_div_bottom = y0 + lane_w
                _dashed_line(surface, C_DASH,
                             (int(x0), int(lane_div_top)),
                             (int(x1), int(lane_div_top)),
                             dash=20, gap=14, w=2)
                _dashed_line(surface, C_DASH,
                             (int(x0), int(lane_div_bottom)),
                             (int(x1), int(lane_div_bottom)),
                             dash=20, gap=14, w=2)

                # Double yellow center line
                pygame.draw.line(surface, C_YELLOW,
                                 (int(x0), int(y0 - 3)),
                                 (int(x1), int(y1 - 3)), 3)
                pygame.draw.line(surface, C_YELLOW,
                                 (int(x0), int(y0 + 3)),
                                 (int(x1), int(y1 + 3)), 3)

            else:  # vertical
                road_left  = x0 - ht + sw
                road_right = x0 + ht - sw

                # Solid white edge lines
                pygame.draw.line(surface, C_WHITE,
                                 (int(road_left),  int(y0)),
                                 (int(road_left),  int(y1)), 2)
                pygame.draw.line(surface, C_WHITE,
                                 (int(road_right), int(y0)),
                                 (int(road_right), int(y1)), 2)

                # Dashed lane dividers
                lane_div_left  = x0 - lane_w
                lane_div_right = x0 + lane_w
                _dashed_line(surface, C_DASH,
                             (int(lane_div_left), int(y0)),
                             (int(lane_div_left), int(y1)),
                             dash=20, gap=14, w=2)
                _dashed_line(surface, C_DASH,
                             (int(lane_div_right), int(y0)),
                             (int(lane_div_right), int(y1)),
                             dash=20, gap=14, w=2)

                # Double yellow center line
                pygame.draw.line(surface, C_YELLOW,
                                 (int(x0 - 3), int(y0)),
                                 (int(x1 - 3), int(y1)), 3)
                pygame.draw.line(surface, C_YELLOW,
                                 (int(x0 + 3), int(y0)),
                                 (int(x1 + 3), int(y1)), 3)

        # ── 6. Intersection zones stay clean above lane markings ─────────
        for inter in data.intersections:
            ix = int(inter.cx - rw // 2 + ox)
            iy = int(inter.cy - rw // 2 + oy)
            pygame.draw.rect(surface, C_INTER, (ix, iy, rw, rw))

        # ── 7. Crosswalks at each intersection entry ─────────────────────
        for inter in data.intersections:
            cx = inter.cx + ox
            cy = inter.cy + oy
            _draw_crosswalk(surface, cx, cy, rw, 'top')
            _draw_crosswalk(surface, cx, cy, rw, 'bottom')
            _draw_crosswalk(surface, cx, cy, rw, 'left')
            _draw_crosswalk(surface, cx, cy, rw, 'right')

        # ── 8. Street names ───────────────────────────────────────────────
        for seg in data.road_segments:
            x0, y0 = seg.start[0] + ox, seg.start[1] + oy
            x1, y1 = seg.end[0]   + ox, seg.end[1]   + oy
            if seg.direction == "horizontal":
                mid_x = (x0 + x1) / 2
                txt = self._f_street.render(seg.name, True, C_WHITE)
                surface.blit(txt, (int(mid_x - txt.get_width() // 2),
                                   int(y0 - txt.get_height() // 2)))
            else:
                mid_y = (y0 + y1) / 2
                txt = self._f_street.render(seg.name, True, C_WHITE)
                txt_rot = pygame.transform.rotate(txt, 90)
                surface.blit(txt_rot,
                             (int(x0 - txt_rot.get_width() // 2),
                              int(mid_y - txt_rot.get_height() // 2)))

    # ── Public API ────────────────────────────────────────────────────────
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

    def get_spawn_points(self) -> List[SpawnPoint]:
        """
        Returns all vehicle spawn points at the screen edges.
        Use these to spawn vehicles and implement wrap-around:
          - Spawn at (spawn_x, spawn_y) moving in `direction`
          - When vehicle reaches (exit_x, exit_y), reset to (spawn_x, spawn_y)
        """
        if self._map_data is None:
            self.generate()
        return self._map_data.spawn_points

    def get_map_size(self) -> Tuple[int, int]:
        """Returns (total_width, total_height) of the map."""
        return self.total_width, self.total_height

    def reset(self):
        """Regenerate the map with the same parameters."""
        self.generate()

# ══════════════════════════════════════════════
#  DEMO  (standalone preview — no simulation)
# ══════════════════════════════════════════════
def _preview_button_rects() -> Tuple[pygame.Rect, pygame.Rect]:
    bw, bh, pad, gap = 100, 42, 18, 10
    play_r = pygame.Rect(pad, pad, bw, bh)
    reset_r = pygame.Rect(pad + bw + gap, pad, bw, bh)
    return play_r, reset_r

def _draw_preview_buttons(surface: pygame.Surface, font: pygame.font.Font,
                          is_playing: bool) -> Tuple[pygame.Rect, pygame.Rect]:
    play_r, reset_r = _preview_button_rects()
    labels = [(play_r, "Pause" if is_playing else "Play"),
              (reset_r, "Reset")]
    for rect, label in labels:
        pygame.draw.rect(surface, (242, 246, 252), rect, border_radius=10)
        pygame.draw.rect(surface, (35, 43, 55), rect, 1, border_radius=10)
        txt = font.render(label, True, (15, 23, 35))
        surface.blit(txt, (rect.x + (rect.w - txt.get_width()) // 2,
                           rect.y + (rect.h - txt.get_height()) // 2))
    return play_r, reset_r

def main():
    pygame.init()
    pygame.display.set_caption("Simulador de Trafico - Mapa")
    COLS, ROWS   = 4, 4
    BLOCK_SIZE   = 160
    ROAD_WIDTH   = 96
    gen = MapGenerator(cols=COLS, rows=ROWS,
                       block_size=BLOCK_SIZE, road_width=ROAD_WIDTH)
    gen.generate()

    screen = pygame.display.set_mode(
        (gen.total_width, gen.total_height), pygame.RESIZABLE)
    clock  = pygame.time.Clock()
    is_playing = True
    logical_size = (gen.total_width, gen.total_height)
    map_surf = pygame.Surface(logical_size)
    btn_font = pygame.font.SysFont("arial", 18, bold=True)

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    is_playing = not is_playing
                elif event.key == pygame.K_r:
                    gen.reset()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                pr, rr = _preview_button_rects()
                if pr.collidepoint(event.pos):
                    is_playing = not is_playing
                elif rr.collidepoint(event.pos):
                    gen.reset()

        gen.draw(map_surf)

        scaled = pygame.transform.smoothscale(map_surf, screen.get_size())
        screen.blit(scaled, (0, 0))
        _draw_preview_buttons(screen, btn_font, is_playing)
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
