"""
simulation.py  -  v3
=====================
Traffic simulation using MapGenerator as the procedural map backend.

What's kept from v1:
  - Vehicle class: texture loading, lane movement, speed model
  - generateVehicles thread
  - Main game loop

What changed:
  - The map is drawn by MapGenerator as a road/intersection model
  - Traffic signals are placed manually per intersection approach and vehicles
    stop at their corresponding red/yellow signal
  - Vehicles keep a physical separation, queue behind slower traffic, and
    change to the parallel same-direction lane only when it is clear
  - Random intersection crashes follow a Poisson arrival process; blocked
    traffic uses a parallel lane or an automatically marked temporary bypass
  - Vehicle spawn coords come from MapGenerator.get_spawn_points()
    → vehicles wrap around: exit one edge → reappear on the opposite side
  - Window size matches the generated map
"""

import random
import time
import threading
import pygame
import sys
import os

from control_panel import ControlPanel
from map_generator import MapGenerator
from traffic_accidents import TrafficAccidentSystem
from traffic_signals import TrafficSignalSystem

# ══════════════════════════════════════════════
#  MAP SETUP
# ══════════════════════════════════════════════
MAP_COLS       = 4
MAP_ROWS       = 4
MAP_BLOCK_SIZE = 160
MAP_ROAD_WIDTH = 96

gen = MapGenerator(cols=MAP_COLS, rows=MAP_ROWS,
                   block_size=MAP_BLOCK_SIZE, road_width=MAP_ROAD_WIDTH)
gen.generate()
MAP_W, MAP_H = gen.get_map_size()

# ══════════════════════════════════════════════
#  VEHICLE SETTINGS
# ══════════════════════════════════════════════
VEHICLE_WIDTHS = {'car': 14, 'motorcycle': 12, 'bus': 14, 'truck': 14}
OTHER_WIDTH_SCALE = 0.6

speeds = {'car': 2.25, 'bus': 1.8, 'truck': 1.8, 'motorcycle': 2.5}

vehicleTypes     = {0: 'car', 1: 'bus', 2: 'truck', 3: 'motorcycle'}
directionNumbers = {0: 'right', 1: 'down', 2: 'left', 3: 'up'}

MAX_VEHICLES = 46
SPEED_MULTIPLIER = 1.0
SPAWN_VEHICLE_TYPE = 'random'
SIGNAL_SECONDS = 8.0

stoppingGap         = 15
movingGap           = 15
decelerationDistance = 120
accelerationRate    = 0.12
decelerationRate    = 0.20
laneChangeTriggerDistance = 85
laneChangeFrontGap = 45
laneChangeRearGap = 55
laneChangeCooldownFrames = 120
physicalClearance = 2

# ══════════════════════════════════════════════
#  SPAWN POINT INDEX
# Organise spawn points by direction so Vehicle can pick
# a starting position that matches the grid lanes.
# ══════════════════════════════════════════════
pygame.init()
simulation = pygame.sprite.Group()
vehicle_lock = threading.RLock()
traffic_signals = TrafficSignalSystem(gen)
traffic_accidents = TrafficAccidentSystem(gen, arrivals_per_minute=2.5)

_spawn_by_dir: dict = {'right': [], 'left': [], 'up': [], 'down': []}
for sp in gen.get_spawn_points():
    _spawn_by_dir[sp.direction].append(sp)

# Per-lane vehicle queues  {direction: {lane_idx: [vehicles]}}
vehicles: dict = {
    'right': {}, 'left': {}, 'up': {}, 'down': {}
}
for d, sps in _spawn_by_dir.items():
    for i, _ in enumerate(sps):
        vehicles[d][i] = []

# ══════════════════════════════════════════════
#  VEHICLE CLASS
# ══════════════════════════════════════════════
class Vehicle(pygame.sprite.Sprite):
    def __init__(self, lane_idx, vehicleClass, direction_number, direction):
        pygame.sprite.Sprite.__init__(self)
        self.lane            = lane_idx
        self.vehicleClass    = vehicleClass
        self.maxSpeed        = speeds[vehicleClass] * random.uniform(0.6, 1.6)
        self.speed           = self.maxSpeed
        self.direction_number = direction_number
        self.direction       = direction
        self.lane_change_cooldown = 0
        self.temporary_detour = None

        # Pick spawn point for this direction + lane
        sp_list = _spawn_by_dir[direction]
        if not sp_list:
            self.kill()
            return
        sp = sp_list[lane_idx % len(sp_list)]
        self.x = sp.spawn_x
        self.y = sp.spawn_y
        self._exit_x  = sp.exit_x
        self._exit_y  = sp.exit_y
        self._spawn_x = sp.spawn_x
        self._spawn_y = sp.spawn_y

        self._load_texture()
        self._place_at_spawn()

        with vehicle_lock:
            if lane_idx not in vehicles[direction]:
                vehicles[direction][lane_idx] = []

            # Keep newly spawned vehicles from stacking on the same lane.
            prev_list = vehicles[direction][lane_idx]
            rect = self.image.get_rect()
            for prev in prev_list:
                prev_rect = prev.image.get_rect()
                if direction == 'right':
                    self.x = min(self.x, prev.x - rect.width - movingGap)
                elif direction == 'left':
                    self.x = max(self.x, prev.x + prev_rect.width + movingGap)
                elif direction == 'down':
                    self.y = min(self.y, prev.y - rect.height - movingGap)
                elif direction == 'up':
                    self.y = max(self.y, prev.y + prev_rect.height + movingGap)

            vehicles[direction][lane_idx].append(self)
            self.index = len(vehicles[direction][lane_idx]) - 1
            simulation.add(self)

    # ── texture ─────────────────────────────────────────────────────────
    def _load_texture(self):
        dir_path = os.path.join("images", "vehicle", self.vehicleClass)
        try:
            files = [f for f in os.listdir(dir_path)
                     if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif'))]
            path = os.path.join(dir_path, random.choice(files)) if files else \
                   os.path.join("images", "vehicle", "others", self.vehicleClass + ".png")
        except Exception:
            path = os.path.join("images", "vehicle", "others", self.vehicleClass + ".png")

        self.image = pygame.image.load(path).convert_alpha()
        orig_w = self.image.get_rect().width
        orig_h = self.image.get_rect().height
        target_w = VEHICLE_WIDTHS.get(self.vehicleClass, int(orig_w * OTHER_WIDTH_SCALE))
        if target_w != orig_w and orig_w > 0:
            scale = target_w / orig_w
            self.image = pygame.transform.scale(
                self.image, (target_w, max(1, int(orig_h * scale))))

        if   self.direction == 'right': self.image = pygame.transform.rotate(self.image, -90)
        elif self.direction == 'down':  self.image = pygame.transform.rotate(self.image, 180)
        elif self.direction == 'left':  self.image = pygame.transform.rotate(self.image,  90)

    # ── movement helpers ─────────────────────────────────────────────────
    def render(self, screen):
        screen.blit(self.image, (self.x, self.y))

    def _place_at_spawn(self):
        rect = self.image.get_rect()
        if self.direction == 'right':
            self.x = self._spawn_x - rect.width - stoppingGap
            self.y = self._spawn_y - rect.height / 2
        elif self.direction == 'left':
            self.x = self._spawn_x + stoppingGap
            self.y = self._spawn_y - rect.height / 2
        elif self.direction == 'down':
            self.x = self._spawn_x - rect.width / 2
            self.y = self._spawn_y - rect.height - stoppingGap
        elif self.direction == 'up':
            self.x = self._spawn_x - rect.width / 2
            self.y = self._spawn_y + stoppingGap

    def _front_position(self):
        if   self.direction == 'right': return self.x + self.image.get_rect().width
        elif self.direction == 'down':  return self.y + self.image.get_rect().height
        elif self.direction == 'left':  return self.x
        return self.y

    def _vehicle_rect(self, x=None, y=None):
        rect = self.image.get_rect()
        return pygame.Rect(
            round(self.x if x is None else x),
            round(self.y if y is None else y),
            rect.width,
            rect.height,
        )

    def _progress_bounds(self, x=None, y=None):
        """Return rear/front positions on an axis that always grows forward."""
        x = self.x if x is None else x
        y = self.y if y is None else y
        rect = self.image.get_rect()
        if self.direction == 'right':
            return x, x + rect.width
        if self.direction == 'left':
            return -(x + rect.width), -x
        if self.direction == 'down':
            return y, y + rect.height
        return -(y + rect.height), -y

    def _lead_vehicle_info(self, lane_idx=None):
        if self.temporary_detour is not None:
            return float('inf'), None

        lane_idx = self.lane if lane_idx is None else lane_idx
        with vehicle_lock:
            lane_list = list(vehicles[self.direction].get(lane_idx, []))

        _, self_front = self._progress_bounds()
        closest_distance = float('inf')
        closest_vehicle = None
        for lead in lane_list:
            if lead is self:
                continue
            if not lead.alive():
                continue
            lead_rear, lead_front = lead._progress_bounds()
            if lead_front <= self_front:
                continue
            distance = lead_rear - self_front - movingGap
            if distance < closest_distance:
                closest_distance = distance
                closest_vehicle = lead
        return closest_distance, closest_vehicle

    def _distance_to_lead_vehicle(self):
        return self._lead_vehicle_info()[0]

    def _parallel_lane(self):
        road_first_lane = (self.lane // 2) * 2
        other_lane = road_first_lane + (1 - self.lane % 2)
        if other_lane not in vehicles[self.direction]:
            return None
        return other_lane

    def _target_lane_position(self, lane_idx):
        sp = _spawn_by_dir[self.direction][lane_idx]
        rect = self.image.get_rect()
        if self.direction in ('right', 'left'):
            return self.x, sp.spawn_y - rect.height / 2
        return sp.spawn_x - rect.width / 2, self.y

    def _near_intersection(self):
        rect = self.image.get_rect()
        center_x = self.x + rect.width / 2
        center_y = self.y + rect.height / 2
        road_index = self.lane // 2
        margin = gen.road_width * 0.8
        for inter in gen.get_intersections():
            if self.direction in ('right', 'left'):
                if inter.row == road_index and abs(center_x - inter.cx) < margin:
                    return True
            elif inter.col == road_index and abs(center_y - inter.cy) < margin:
                return True
        return False

    def _target_lane_is_clear(self, lane_idx, current_distance):
        target_x, target_y = self._target_lane_position(lane_idx)
        target_rect = self._vehicle_rect(target_x, target_y).inflate(
            physicalClearance * 2, physicalClearance * 2
        )
        self_rear, self_front = self._progress_bounds()
        front_clearance = float('inf')
        rear_clearance = float('inf')

        with vehicle_lock:
            target_vehicles = list(vehicles[self.direction].get(lane_idx, []))

        for other in target_vehicles:
            if other is self or not other.alive():
                continue
            if target_rect.colliderect(other._vehicle_rect()):
                return False
            other_rear, other_front = other._progress_bounds()
            if other_rear >= self_front:
                front_clearance = min(front_clearance, other_rear - self_front)
            elif other_front <= self_rear:
                rear_clearance = min(rear_clearance, self_rear - other_front)
            else:
                return False

        needed_front = max(laneChangeFrontGap, current_distance + movingGap + 20)
        return front_clearance >= needed_front and rear_clearance >= laneChangeRearGap

    def _change_lane(self, lane_idx):
        target_x, target_y = self._target_lane_position(lane_idx)
        with vehicle_lock:
            old_lane = vehicles[self.direction].get(self.lane, [])
            if self in old_lane:
                old_lane.remove(self)
            vehicles[self.direction].setdefault(lane_idx, []).append(self)
            self.lane = lane_idx

        sp = _spawn_by_dir[self.direction][lane_idx]
        self._spawn_x = sp.spawn_x
        self._spawn_y = sp.spawn_y
        self._exit_x = sp.exit_x
        self._exit_y = sp.exit_y
        self.x, self.y = target_x, target_y
        self.lane_change_cooldown = laneChangeCooldownFrames

    def _try_change_lane(self, distance_to_lead, lead):
        if (
            lead is None
            or self.lane_change_cooldown > 0
            or distance_to_lead > laneChangeTriggerDistance
            or self._near_intersection()
        ):
            return False

        desired_speed = self.maxSpeed * SPEED_MULTIPLIER
        if desired_speed <= lead.speed + 0.25:
            return False

        target_lane = self._parallel_lane()
        if target_lane is None or not self._target_lane_is_clear(target_lane, distance_to_lead):
            return False

        self._change_lane(target_lane)
        return True

    def _activate_temporary_detour(self, detour):
        if self.direction in ('right', 'left'):
            target_x, target_y = self.x, detour.lateral_position - self.image.get_height() / 2
        else:
            target_x, target_y = detour.lateral_position - self.image.get_width() / 2, self.y
        if not self._position_is_clear(target_x, target_y):
            return False
        self.x, self.y = target_x, target_y
        self.temporary_detour = detour
        self.lane_change_cooldown = laneChangeCooldownFrames
        return True

    def _try_avoid_accident(self, distance_to_accident, accident):
        if (
            accident is None
            or self.temporary_detour is not None
            or distance_to_accident > traffic_accidents.DETOUR_TRIGGER_DISTANCE
        ):
            return False

        target_lane = self._parallel_lane()
        if (
            target_lane is not None
            and not traffic_accidents.lane_blocked_at(
                accident.intersection, self.direction, target_lane
            )
            and self._target_lane_is_clear(target_lane, distance_to_accident)
        ):
            self._change_lane(target_lane)
            return True

        detour = traffic_accidents.detour_for(accident)
        return detour is not None and self._activate_temporary_detour(detour)

    def _maybe_finish_temporary_detour(self):
        detour = self.temporary_detour
        if detour is None:
            return
        front = self._front_position()
        passed = front > detour.clear_after if self.direction in ('right', 'down') \
            else front < detour.clear_after
        if not passed:
            return

        target_x, target_y = self._target_lane_position(self.lane)
        if self._position_is_clear(target_x, target_y):
            self.x, self.y = target_x, target_y
            self.temporary_detour = None

    def _position_is_clear(self, x=None, y=None):
        candidate = self._vehicle_rect(x, y).inflate(
            physicalClearance * 2, physicalClearance * 2
        )
        if not traffic_accidents.position_is_clear(candidate):
            return False
        with vehicle_lock:
            active_vehicles = list(simulation)
        for other in active_vehicles:
            if other is self or not other.alive():
                continue
            if candidate.colliderect(other._vehicle_rect()):
                return False
        return True

    def _collision_free_distance(self, requested_distance):
        """Limit movement so vehicle rectangles never overlap."""
        if requested_distance <= 0:
            return 0

        def position_after(distance):
            if self.direction == 'right':
                return self.x + distance, self.y
            if self.direction == 'left':
                return self.x - distance, self.y
            if self.direction == 'down':
                return self.x, self.y + distance
            return self.x, self.y - distance

        end_x, end_y = position_after(requested_distance)
        if self._position_is_clear(end_x, end_y):
            return requested_distance

        low, high = 0.0, requested_distance
        for _ in range(10):
            middle = (low + high) / 2
            test_x, test_y = position_after(middle)
            if self._position_is_clear(test_x, test_y):
                low = middle
            else:
                high = middle
        return low

    def _move_by(self, distance):
        if   self.direction == 'right': self.x += distance
        elif self.direction == 'down':  self.y += distance
        elif self.direction == 'left':  self.x -= distance
        elif self.direction == 'up':    self.y -= distance

    def _has_exited(self):
        """Returns True when the vehicle has left the map on the far side."""
        if   self.direction == 'right': return self.x > MAP_W + 60
        elif self.direction == 'left':  return self.x + self.image.get_rect().width < -60
        elif self.direction == 'down':  return self.y > MAP_H + 60
        elif self.direction == 'up':    return self.y + self.image.get_rect().height < -60
        return False

    def _wrap(self):
        """Teleport back to the spawn edge (wrap-around)."""
        old_x, old_y = self.x, self.y
        self._place_at_spawn()
        if not self._position_is_clear():
            self.x, self.y = old_x, old_y
            self.speed = 0
            return False
        return True

    def move(self):
        if self.lane_change_cooldown > 0:
            self.lane_change_cooldown -= 1
        self._maybe_finish_temporary_detour()

        # Wrap-around: if the vehicle exited, teleport back
        if self._has_exited():
            self._wrap()
            return

        ignored_accidents = (
            self.temporary_detour.accident_ids
            if self.temporary_detour is not None
            else ()
        )
        dist_accident, accident = traffic_accidents.nearest_block(
            self.direction,
            self.lane,
            self._front_position(),
            ignored_accidents,
        )
        if self._try_avoid_accident(dist_accident, accident):
            dist_accident, accident = traffic_accidents.nearest_block(
                self.direction,
                self.lane,
                self._front_position(),
                self.temporary_detour.accident_ids
                if self.temporary_detour is not None
                else (),
            )

        dist_lead, lead = self._lead_vehicle_info()
        if self.temporary_detour is None and self._try_change_lane(dist_lead, lead):
            dist_lead, lead = self._lead_vehicle_info()

        if self.temporary_detour is None:
            dist_signal = traffic_signals.distance_to_stop(
                self.direction,
                self.lane,
                self._front_position(),
                SIGNAL_SECONDS,
            )
        else:
            dist_signal = float('inf')
        available = min(dist_lead, dist_signal, dist_accident)

        if available <= 0:
            target_speed = 0
        elif available < decelerationDistance:
            target_speed = self.maxSpeed * SPEED_MULTIPLIER * (available / decelerationDistance)
        else:
            target_speed = self.maxSpeed * SPEED_MULTIPLIER

        if self.speed < target_speed:
            self.speed = min(target_speed, self.speed + accelerationRate)
        else:
            self.speed = max(target_speed, self.speed - decelerationRate)

        move_dist = min(self.speed, max(0, available))
        if move_dist > 0:
            move_dist = self._collision_free_distance(move_dist)
            self._move_by(move_dist)
        if move_dist < 0.05:
            self.speed = 0

def spawn_vehicle(vehicle_type=None, map_position=None):
    """Spawn a vehicle normally or snap a dropped vehicle to the nearest lane."""
    if vehicle_type in (None, 'random'):
        vehicle_type = vehicleTypes[random.randint(0, 3)]

    if map_position is None:
        direction_number = random.randint(0, 3)
        direction = directionNumbers[direction_number]
        lane_count = len(_spawn_by_dir[direction])
        if lane_count == 0:
            return None
        lane_idx = random.randint(0, lane_count - 1)
    else:
        mx, my = map_position
        candidates = []
        for direction, points in _spawn_by_dir.items():
            for lane_idx, point in enumerate(points):
                distance = abs(my - point.spawn_y) if direction in ('right', 'left') \
                    else abs(mx - point.spawn_x)
                candidates.append((distance, direction, lane_idx, point))
        if not candidates:
            return None
        _, direction, lane_idx, point = min(candidates, key=lambda item: item[0])
        direction_number = next(
            number for number, name in directionNumbers.items() if name == direction
        )

    vehicle = Vehicle(lane_idx, vehicle_type, direction_number, direction)
    if map_position is not None and vehicle.alive():
        mx, my = map_position
        rect = vehicle.image.get_rect()
        if direction in ('right', 'left'):
            vehicle.x = mx - rect.width / 2
            vehicle.y = point.spawn_y - rect.height / 2
        else:
            vehicle.x = point.spawn_x - rect.width / 2
            vehicle.y = my - rect.height / 2
        if not vehicle._position_is_clear():
            _remove_vehicle(vehicle)
            return None
    return vehicle


def _remove_vehicle(vehicle):
    with vehicle_lock:
        lane = vehicles.get(vehicle.direction, {}).get(vehicle.lane, [])
        if vehicle in lane:
            lane.remove(vehicle)
        vehicle.kill()


def _trim_vehicles(limit):
    with vehicle_lock:
        excess = max(0, len(simulation) - limit)
        to_remove = list(simulation)[-excess:] if excess else []
    for vehicle in to_remove:
        _remove_vehicle(vehicle)


def _clear_vehicles():
    with vehicle_lock:
        for direction_lanes in vehicles.values():
            for lane in direction_lanes.values():
                lane.clear()
        simulation.empty()


def generateVehicles():
    while True:
        with vehicle_lock:
            at_capacity = len(simulation) >= MAX_VEHICLES
        if at_capacity:
            time.sleep(0.5)
            continue

        spawn_vehicle(SPAWN_VEHICLE_TYPE)
        time.sleep(round(random.uniform(0.15, 2.0), 2))

# ══════════════════════════════════════════════
#  VIEW AND OVERLAY HELPERS
# ══════════════════════════════════════════════
def _overlay_button_rects(map_area):
    bw, bh, pad, gap = 100, 42, 18, 10
    play_r = pygame.Rect(map_area.x + pad, map_area.y + pad, bw, bh)
    reset_r = pygame.Rect(map_area.x + pad + bw + gap, map_area.y + pad, bw, bh)
    return play_r, reset_r

def _draw_overlay_buttons(surface, font, is_playing, map_area):
    play_r, reset_r = _overlay_button_rects(map_area)
    labels = [(play_r, "Pause" if is_playing else "Play"),
              (reset_r, "Reset")]
    for rect, label in labels:
        pygame.draw.rect(surface, (242, 246, 252), rect, border_radius=10)
        pygame.draw.rect(surface, (35, 43, 55), rect, 1, border_radius=10)
        txt = font.render(label, True, (15, 23, 35))
        surface.blit(txt, (rect.x + (rect.w - txt.get_width()) // 2,
                           rect.y + (rect.h - txt.get_height()) // 2))
    return play_r, reset_r


def _layout(screen, panel):
    width, height = screen.get_size()
    panel_width = min(panel.WIDTH, max(220, width // 3))
    panel_rect = pygame.Rect(0, 0, panel_width, height)
    map_area = pygame.Rect(panel_width, 0, max(1, width - panel_width), height)
    scale = min(map_area.width / MAP_W, map_area.height / MAP_H)
    scaled_size = (max(1, int(MAP_W * scale)), max(1, int(MAP_H * scale)))
    map_rect = pygame.Rect((0, 0), scaled_size)
    map_rect.center = map_area.center
    return panel_rect, map_area, map_rect


def _screen_to_map(position, map_rect):
    if not map_rect.collidepoint(position):
        return None
    return (
        (position[0] - map_rect.x) * MAP_W / map_rect.width,
        (position[1] - map_rect.y) * MAP_H / map_rect.height,
    )


def _simulation_stats():
    with vehicle_lock:
        active = list(simulation)
    counts = {'car': 0, 'motorcycle': 0, 'truck': 0, 'bus': 0}
    for vehicle in active:
        counts[vehicle.vehicleClass] = counts.get(vehicle.vehicleClass, 0) + 1
    return {
        'total': len(active),
        'cars': counts['car'],
        'motorcycles': counts['motorcycle'],
        'trucks': counts['truck'],
        'buses': counts['bus'],
        'signals': len(traffic_signals),
        'accidents': len(traffic_accidents),
        'accident_model': traffic_accidents.model_label,
        'congestion': min(100, round(len(active) / 130 * 100)),
        'intersections': len(gen.get_intersections()),
        'roads': len(gen.get_road_segments()),
    }


def _reset_simulation():
    gen.reset()
    _clear_vehicles()
    traffic_signals.clear()
    traffic_signals.refresh_targets()
    traffic_accidents.clear()
    traffic_accidents.refresh_slots()

# ══════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════
def main():
    global MAX_VEHICLES, SPEED_MULTIPLIER, SPAWN_VEHICLE_TYPE, SIGNAL_SECONDS

    panel = ControlPanel()
    initial_size = (MAP_W + panel.WIDTH, min(MAP_H, 850))
    screen = pygame.display.set_mode(initial_size, pygame.RESIZABLE)
    pygame.display.set_caption("Simulador de Tráfico")

    btn_font     = pygame.font.SysFont("arial", 18, bold=True)

    logical_size = (MAP_W, MAP_H)
    map_surf     = pygame.Surface(logical_size)
    clock        = pygame.time.Clock()
    is_playing   = True

    # Start vehicle generation thread
    t2 = threading.Thread(name="generateVehicles", target=generateVehicles, daemon=True)
    t2.start()

    while True:
        frame_dt = clock.tick(60) / 1000.0
        panel_rect, map_area, map_rect = _layout(screen, panel)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)

            panel_action = panel.handle_event(event)
            if panel_action:
                action = panel_action['action']
                if action == 'reset':
                    _reset_simulation()
                elif action == 'drop_vehicle':
                    map_position = _screen_to_map(panel_action['pos'], map_rect)
                    if map_position is not None:
                        panel.max_vehicles = min(100, max(panel.max_vehicles, len(simulation) + 1))
                        spawn_vehicle(panel.selected_vehicle_key, map_position)
                elif action == 'drop_signal':
                    map_position = _screen_to_map(panel_action['pos'], map_rect)
                    if map_position is not None:
                        traffic_signals.place_near(map_position)
                if action not in ('panel_clicked',):
                    continue

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit()
                elif event.key == pygame.K_SPACE:
                    is_playing = not is_playing
                elif event.key == pygame.K_r:
                    _reset_simulation()
                elif event.key == pygame.K_c:
                    with vehicle_lock:
                        occupied_rects = [vehicle._vehicle_rect() for vehicle in simulation]
                    traffic_accidents.generate_random(occupied_rects)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                pr, rr = _overlay_button_rects(map_area)
                if pr.collidepoint(event.pos):
                    is_playing = not is_playing
                elif rr.collidepoint(event.pos):
                    _reset_simulation()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                map_position = _screen_to_map(event.pos, map_rect)
                if map_position is not None:
                    if not traffic_accidents.remove_near(map_position):
                        traffic_signals.remove_near(map_position)

        MAX_VEHICLES = panel.max_vehicles
        SPEED_MULTIPLIER = panel.speed_multiplier
        SPAWN_VEHICLE_TYPE = panel.selected_vehicle_key
        SIGNAL_SECONDS = panel.signal_seconds
        _trim_vehicles(MAX_VEHICLES)

        # ── Draw map model ──
        gen.draw(map_surf)
        if is_playing:
            with vehicle_lock:
                occupied_rects = [vehicle._vehicle_rect() for vehicle in simulation]
            traffic_accidents.update(frame_dt, occupied_rects)
        if panel.drag_payload == 'signal':
            traffic_signals.draw_targets(map_surf)
        traffic_signals.draw(map_surf, SIGNAL_SECONDS)
        traffic_accidents.draw(map_surf)

        # ── Draw & move vehicles ──
        with vehicle_lock:
            active_vehicles = list(simulation)

        if is_playing:
            for vehicle in active_vehicles:
                map_surf.blit(vehicle.image, (vehicle.x, vehicle.y))
                vehicle.move()
        else:
            for vehicle in active_vehicles:
                map_surf.blit(vehicle.image, (vehicle.x, vehicle.y))

        # ── Draw map and panel side by side ──
        screen.fill((18, 25, 36))
        scaled = pygame.transform.smoothscale(map_surf, map_rect.size)
        screen.blit(scaled, map_rect.topleft)
        _draw_overlay_buttons(screen, btn_font, is_playing, map_area)
        panel.draw(screen, panel_rect, _simulation_stats())
        panel.draw_drag_preview(screen)
        pygame.display.flip()

if __name__ == "__main__":
    main()
