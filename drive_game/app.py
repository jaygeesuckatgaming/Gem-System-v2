"""Ursina renderer for Gem Drive.

Defaults to simple cubes, but custom car/traffic models can be dropped into
`models/cars/` and enabled through config (or the Games tab). The camera
defaults to a wide pack shot that zooms out to keep every active car in frame.
"""

from __future__ import annotations

import json
import math
import queue
import threading
import time as wall_clock
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ursina import (
    Entity,
    Sky,
    Text,
    Ursina,
    Vec3,
    application,
    camera,
    color,
    destroy,
    scene,
    time,
    window,
)

from . import assets, tuning
from .sim import DriveSim, lane_x

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _lerp(current: float, target: float, t: float) -> float:
    return current + (target - current) * max(0.0, min(1.0, t))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class EventForwarder:
    """Posts gameplay events to main.py without blocking the render loop."""

    FORWARDED = {"crash", "leader", "milestone", "session_start"}

    def __init__(self, url: str) -> None:
        self.url = url
        self.queue: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue(maxsize=50)
        thread = threading.Thread(target=self._run, name="gem-drive-events", daemon=True)
        thread.start()

    def submit(self, events: List[Dict[str, Any]]) -> None:
        for event in events:
            if event.get("demo") or event.get("type") not in self.FORWARDED:
                continue
            try:
                self.queue.put_nowait(event)
            except queue.Full:
                pass

    def _run(self) -> None:
        while True:
            event = self.queue.get()
            if event is None:
                return
            try:
                request = urllib.request.Request(
                    self.url,
                    data=json.dumps(event).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(request, timeout=2.0).read()
            except Exception:
                pass


class DriveView:
    """Owns the Ursina entities and translates sim snapshots into visuals."""

    def __init__(
        self,
        sim: DriveSim,
        event_url: Optional[str] = None,
        car_model: str = "",
        traffic_model: str = "",
        player_model_dir: str = "models/cars/players",
        model_scale: float = 0.0,
        model_yaw: float = 0.0,
        model_y_offset: float = 0.0,
        camera_mode: str = "fixed",
        camera_offset: Tuple[float, float, float] = (0.0, 32.0, -100.0),
        camera_look: Tuple[float, float, float] = (0.0, 1.0, 30.0),
    ) -> None:
        self.sim = sim
        self.event_url = event_url
        self.forwarder = EventForwarder(event_url) if event_url else None
        camera_mode = str(camera_mode or "fixed").strip().lower()
        if camera_mode not in ("fixed", "wide", "leader", "orbit"):
            camera_mode = "fixed"
        self.camera_mode = camera_mode
        self.camera_locked = camera_mode == "fixed"
        self.camera_offset = tuple(float(value) for value in camera_offset)
        self.camera_look = tuple(float(value) for value in camera_look)
        self.orbit_angle = 0.0
        self.toast = ""
        self.toast_until = 0.0
        self._hud_timer = 0.0
        self._had_players = False
        self._camera_snap = False
        self._snapshot: Dict[str, Any] = sim.snapshot()

        self.car_model_path = assets.resolve_model_path(car_model, PROJECT_ROOT)
        self.traffic_model_path = assets.resolve_model_path(traffic_model, PROJECT_ROOT)
        self.player_model_dir = assets.resolve_model_dir(player_model_dir, PROJECT_ROOT)
        self.model_scale = float(model_scale or 0.0)
        self.model_yaw = float(model_yaw or 0.0)
        self.model_y_offset = float(model_y_offset or 0.0)
        self._player_model_cache: Dict[str, Optional[Path]] = {}
        self._warned_models: set = set()

        if car_model and self.car_model_path is None:
            self._warn_model(car_model, f"car model not found or unsupported: {car_model}")
        if traffic_model and self.traffic_model_path is None:
            self._warn_model(traffic_model, f"traffic model not found or unsupported: {traffic_model}")

        self.players: Dict[str, Entity] = {}
        self.labels: Dict[str, Text] = {}
        self.traffic: Dict[int, Entity] = {}
        self._dashes: List[Tuple[float, Entity]] = []
        self._trees: List[Tuple[float, Entity]] = []

        self._build_world()
        self._build_hud()

        if self.forwarder:
            self.forwarder.submit([{"type": "session_start", "ts": 0.0}])

    # -- models ------------------------------------------------------------
    def _warn_model(self, key: str, message: str) -> None:
        if key in self._warned_models:
            return
        self._warned_models.add(key)
        print(f"[GAME] {message}", flush=True)

    def _load_mesh(self, path: Path):
        try:
            if path.suffix.lower() == ".obj":
                triangulated = assets.triangulate_obj_file(path)
                if triangulated != path:
                    self._warn_model(
                        f"tri:{path}",
                        f"triangulated quads for Ursina: {triangulated.name}",
                    )
                    path = triangulated
            from ursina.mesh_importer import load_model

            mesh = load_model(path.name, path=path.parent, use_deepcopy=True)
        except Exception as exc:
            self._warn_model(str(path), f"failed to load {path.name}: {exc}")
            return None
        if mesh is None:
            self._warn_model(str(path), f"could not load model: {path}")
        return mesh

    def _player_model_path(self, user: str) -> Optional[Path]:
        if user in self._player_model_cache:
            return self._player_model_cache[user]
        path = assets.find_player_model(user, self.player_model_dir)
        if path is None:
            path = self.car_model_path
        self._player_model_cache[user] = path
        return path

    def _make_model_visual(self, path: Path, root: Entity) -> Optional[Dict[str, Any]]:
        """Load, scale and place a model under `root`. Returns layout info."""
        mesh = self._load_mesh(path)
        if mesh is None:
            return None

        visual = None
        try:
            visual = Entity(model=mesh)
            if path.suffix.lower() == ".obj":
                texture_path = assets.find_obj_texture(path)
                if texture_path is not None:
                    try:
                        from ursina.texture_importer import load_texture

                        texture = load_texture(
                            texture_path.name, path=texture_path.parent
                        )
                        if texture is not None:
                            visual.texture = texture
                            self._warn_model(
                                f"tex:{texture_path}",
                                f"using texture {texture_path.name}",
                            )
                    except Exception as exc:
                        self._warn_model(
                            f"tex:{texture_path}",
                            f"failed to load texture {texture_path.name}: {exc}",
                        )
            bounds = visual.model_bounds
            size = bounds.size
            if abs(size.x) < 1e-6 and abs(size.y) < 1e-6 and abs(size.z) < 1e-6:
                self._warn_model(str(path), f"model has no bounds: {path.name}")
                destroy(visual)
                return None

            scale = assets.fit_scale(size.x, size.z, tuning.CAR_LENGTH, self.model_scale)
            yaw = self.model_yaw
            if not yaw and assets.needs_yaw(size.x, size.z):
                yaw = 90.0

            offset = Vec3(
                -bounds.center.x * scale,
                -bounds.start.y * scale + self.model_y_offset,
                -bounds.center.z * scale,
            )
            pivot = Entity(parent=root, rotation_y=yaw)
            visual.parent = pivot
            visual.scale = scale
            visual.position = offset

            length = max(abs(size.x), abs(size.z)) * scale
            width = min(abs(size.x), abs(size.z)) * scale
            top = offset.y + abs(size.y) * scale
            return {
                "visual": visual,
                "pivot": pivot,
                "label_height": max(4.2, top + 1.4),
                "model_length": length,
                "model_width": width,
            }
        except Exception as exc:
            self._warn_model(str(path), f"failed to place {path.name}: {exc}")
            if visual is not None:
                try:
                    destroy(visual)
                except Exception:
                    pass
            return None

    def _create_player_entity(self, user: str, rgb: Tuple[int, int, int]) -> Entity:
        root = Entity()
        info = None
        model_path = self._player_model_path(user)
        if model_path is not None:
            info = self._make_model_visual(model_path, root)

        is_custom = info is not None
        if info is None:
            visual = Entity(
                parent=root,
                model="cube",
                scale=(tuning.CAR_WIDTH, 0.9, tuning.CAR_LENGTH),
                position=(0, 0.55, 0),
                color=color.rgb32(*rgb),
            )
            Entity(
                parent=visual,
                model="cube",
                scale=(0.85, 0.5, 0.5),
                position=(0, 0.55, 0.05),
                color=color.rgb32(35, 40, 50),
            )
            info = {
                "visual": visual,
                "pivot": None,
                "label_height": 4.2,
                "model_length": tuning.CAR_LENGTH,
                "model_width": tuning.CAR_WIDTH,
            }

        root.visual = info["visual"]
        root.is_custom_model = is_custom
        root.label_height = info["label_height"]
        root.model_length = info["model_length"]
        root.model_width = info["model_width"]
        root.plate = Entity(
            parent=root,
            model="cube",
            scale=(
                max(tuning.CAR_WIDTH + 0.9, info["model_width"] + 0.8),
                0.03,
                max(tuning.CAR_LENGTH + 0.9, info["model_length"] + 0.8),
            ),
            position=(0, 0.02, 0),
            color=color.rgb32(*rgb),
        )
        return root

    def _create_traffic_entity(self, traffic: Dict[str, Any]) -> Entity:
        root = Entity()
        info = None
        if self.traffic_model_path is not None:
            info = self._make_model_visual(self.traffic_model_path, root)

        if info is None:
            visual = Entity(
                parent=root,
                model="cube",
                scale=(tuning.CAR_WIDTH, 0.85, tuning.CAR_LENGTH),
                position=(0, 0.5, 0),
                color=color.rgb32(*traffic["color"]),
            )
            info = {"visual": visual, "pivot": None}
        root.visual = info["visual"]
        return root

    # -- world -------------------------------------------------------------
    def _build_world(self) -> None:
        camera.clip_plane_far = 4000
        camera.clip_plane_near = 0.1
        Sky(color=color.rgb32(150, 190, 230))
        try:
            scene.fog_color = color.rgb32(165, 195, 225)
            scene.fog_density = 0.0015
        except Exception:
            pass

        self.ground = Entity(
            model="cube",
            scale=(520, 0.2, 1400),
            position=(0, -0.45, 0),
            color=color.rgb32(58, 92, 68),
        )
        self.road = Entity(
            model="cube",
            scale=(tuning.ROAD_WIDTH, 0.1, 1400),
            position=(0, -0.05, 0),
            color=color.rgb32(48, 48, 54),
        )
        self.edge_left = Entity(
            model="cube",
            scale=(0.22, 0.06, 1400),
            position=(-tuning.ROAD_WIDTH / 2, 0.01, 0),
            color=color.rgb32(225, 225, 200),
        )
        self.edge_right = Entity(
            model="cube",
            scale=(0.22, 0.06, 1400),
            position=(tuning.ROAD_WIDTH / 2, 0.01, 0),
            color=color.rgb32(225, 225, 200),
        )

        dash_spacing = 14.0
        for divider in range(1, tuning.LANES):
            x = lane_x(divider) - tuning.LANE_WIDTH / 2
            for index in range(24):
                dash = Entity(
                    model="cube",
                    scale=(0.2, 0.04, 5.0),
                    position=(x, 0.02, index * dash_spacing),
                    color=color.rgb32(220, 220, 180),
                )
                self._dashes.append((index * dash_spacing, dash))

        for side in (-1, 1):
            x = side * (tuning.ROAD_WIDTH / 2 + 5.0)
            for index in range(24):
                tree = Entity(
                    model="cube",
                    scale=(1.4, 4.2, 1.4),
                    position=(x, 1.9, index * 26.0),
                    color=color.rgb32(40, 90, 55),
                )
                self._trees.append((index * 26.0, tree))

    def _build_hud(self) -> None:
        self.hud_title = Text(
            parent=camera.ui,
            text="<orange>GEM DRIVE</orange>  <white>chat highway</white>",
            position=(-0.86, 0.47),
            scale=1.15,
        )
        camera_help = (
            "camera fixed"
            if self.camera_locked
            else "F1 wide  F2 leader  F3 orbit"
        )
        self.hud_help = Text(
            parent=camera.ui,
            text=(
                "!l left  !r right  !f faster  !s slower  !b brake  !j join   |   "
                f"{camera_help}  P pause  R reset"
            ),
            position=(-0.86, 0.43),
            scale=0.72,
            color=color.rgb32(225, 225, 225),
        )
        self.hud_board = Text(
            parent=camera.ui,
            text="",
            position=(-0.86, 0.37),
            scale=0.78,
            color=color.rgb32(240, 240, 240),
        )
        self.hud_status = Text(
            parent=camera.ui,
            text="",
            position=(-0.86, -0.46),
            scale=0.78,
            color=color.rgb32(220, 220, 220),
        )
        self.hud_toast = Text(
            parent=camera.ui,
            text="",
            position=(0, 0.27),
            origin=(0, 0),
            scale=1.25,
            color=color.rgb32(255, 225, 120),
        )
        self.hud_paused = Text(
            parent=camera.ui,
            text="<red>PAUSED</red>",
            position=(0, 0.02),
            origin=(0, 0),
            scale=2.4,
        )
        self.hud_paused.enabled = False

    # -- per-frame ---------------------------------------------------------
    def update(self) -> None:
        dt = min(time.dt, 0.1)
        self.sim.tick(dt)
        self._snapshot = self.sim.snapshot()
        events = self.sim.drain_events()
        self._handle_events(events)
        if self.forwarder:
            self.forwarder.submit(events)
        self._sync_entities()
        self._update_world()
        self._update_camera(dt)
        self._hud_timer -= dt
        if self._hud_timer <= 0.0:
            self._hud_timer = 0.25
            self._update_hud()

    def _handle_events(self, events: List[Dict[str, Any]]) -> None:
        for event in events:
            if event.get("type") == "crash":
                self.toast = f"{event.get('user', 'someone')} crashed!"
                self.toast_until = wall_clock.monotonic() + 3.5
            elif event.get("type") == "leader":
                self.toast = f"{event.get('user', 'someone')} takes the lead!"
                self.toast_until = wall_clock.monotonic() + 3.5

    def _sync_entities(self) -> None:
        seen_players = set()
        for player in self._snapshot["players"]:
            user = player["user"]
            seen_players.add(user)
            entity = self.players.get(user)
            if entity is None:
                entity = self._create_player_entity(user, player["color"])
                self.players[user] = entity

            alive = player["alive"]
            entity.position = (player["x"], 0.0, player["z"])
            entity.rotation_y = 0
            entity.rotation_z = 0 if alive else 18

            visual = getattr(entity, "visual", None)
            if visual is not None:
                if not alive:
                    visual.color = color.rgb32(105, 105, 112)
                elif getattr(entity, "is_custom_model", False):
                    visual.color = color.white
                else:
                    visual.color = color.rgb32(*player["color"])
            plate = getattr(entity, "plate", None)
            if plate is not None:
                plate.color = (
                    color.rgb32(*player["color"]) if alive else color.rgb32(90, 90, 95)
                )

            label = self.labels.get(user)
            if label is None:
                label = Text(
                    text=user,
                    parent=scene,
                    position=(player["x"], entity.label_height, player["z"]),
                    scale=24,
                    billboard=True,
                    origin=(0, 0),
                    color=color.white,
                )
                self.labels[user] = label
            label.position = (player["x"], entity.label_height, player["z"])
            label.color = color.white if alive else color.rgb32(170, 170, 175)

        for user in list(self.players):
            if user not in seen_players:
                destroy(self.players.pop(user))
                label = self.labels.pop(user, None)
                if label is not None:
                    destroy(label)

        seen_traffic = set()
        for traffic in self._snapshot["traffic"]:
            traffic_id = traffic["id"]
            seen_traffic.add(traffic_id)
            entity = self.traffic.get(traffic_id)
            if entity is None:
                entity = self._create_traffic_entity(traffic)
                self.traffic[traffic_id] = entity
            entity.position = (lane_x(traffic["lane"]), 0.0, traffic["z"])

        for traffic_id in list(self.traffic):
            if traffic_id not in seen_traffic:
                destroy(self.traffic.pop(traffic_id))

    def _update_world(self) -> None:
        pack = self._snapshot["pack"]
        center_z = pack["center_z"] or 0.0
        self.ground.position = (0, -0.45, center_z)
        self.road.position = (0, -0.05, center_z)
        self.edge_left.position = (-tuning.ROAD_WIDTH / 2, 0.01, center_z)
        self.edge_right.position = (tuning.ROAD_WIDTH / 2, 0.01, center_z)

        base = math.floor((pack["min_z"] - 120.0) / 336.0) * 336.0
        for offset, dash in self._dashes:
            dash.z = base + offset
            while dash.z < pack["min_z"] - 120.0:
                dash.z += 336.0

        tree_base = math.floor((pack["min_z"] - 140.0) / 624.0) * 624.0
        for offset, tree in self._trees:
            tree.z = tree_base + offset
            while tree.z < pack["min_z"] - 140.0:
                tree.z += 624.0

    def _update_camera(self, dt: float) -> None:
        pack = self._snapshot["pack"]
        players = [p for p in self._snapshot["players"] if p["alive"]]
        if not players:
            # The world is centred at the origin while the road is empty, so
            # park the camera there too. Leaving it at the old pack position
            # made the first rejoin lerp across thousands of units (and could
            # flip the view upside down on the way).
            self._had_players = False
            self._camera_snap = True
            camera.position = Vec3(0, 24, -70)
            camera.look_at(Vec3(0, 1, 30), up=Vec3(0, 1, 0))
            return

        if not self._had_players:
            self._had_players = True
            self._camera_snap = True

        mean_x = sum(p["x"] for p in players) / len(players)
        min_z = pack["min_z"]
        max_z = pack["max_z"]
        center_z = pack["center_z"]
        spread = _clamp(
            max(40.0, max_z - min_z),
            tuning.PACK_CAMERA_MIN_SPREAD,
            tuning.PACK_CAMERA_MAX_SPREAD,
        )

        if self.camera_mode == "fixed":
            position_tuple, look_tuple = assets.fixed_camera_pose(
                mean_x, center_z, self.camera_offset, self.camera_look
            )
            position = Vec3(*position_tuple)
            look_at = Vec3(*look_tuple)
        elif self.camera_mode == "leader":
            leader = self._snapshot["leaderboard"][0]["user"] if self._snapshot["leaderboard"] else None
            target = next((p for p in players if p["user"] == leader), players[0])
            position = Vec3(target["x"], 5.5, target["z"] - 12.0)
            look_at = Vec3(target["x"], 0.8, target["z"] + 4.0)
        elif self.camera_mode == "orbit":
            self.orbit_angle += dt * 0.12
            radius = _clamp(28.0 + spread * 0.25, 30.0, 90.0)
            position = Vec3(
                mean_x + math.sin(self.orbit_angle) * radius,
                13.0 + spread * 0.12,
                center_z + math.cos(self.orbit_angle) * radius,
            )
            look_at = Vec3(mean_x, 0.8, center_z)
        else:
            distance = _clamp(
                34.0 + spread * 0.85,
                tuning.PACK_CAMERA_MIN_DISTANCE,
                tuning.PACK_CAMERA_MAX_DISTANCE,
            )
            height = 11.0 + spread * 0.24
            position = Vec3(mean_x, height, min_z - distance)
            look_at = Vec3(mean_x, 1.0, center_z + 20.0 + spread * 0.30)

        if self._camera_snap:
            camera.position = position
            self._camera_snap = False
        else:
            blend = min(1.0, dt * tuning.PACK_CAMERA_SMOOTHING)
            current = camera.position
            camera.position = Vec3(
                _lerp(current.x, position.x, blend),
                _lerp(current.y, position.y, blend),
                _lerp(current.z, position.z, blend),
            )
        # Always pass world up. Ursina's look_at() defaults to the camera's
        # *current* up vector, so one rolled frame would persist forever.
        camera.look_at(look_at, up=Vec3(0, 1, 0))

    def _update_hud(self) -> None:
        snapshot = self._snapshot
        board_lines = ["<orange>TOP DRIVERS</orange>"]
        for index, row in enumerate(snapshot["leaderboard"][:5], start=1):
            name = row["user"][:12]
            best = row["best"] or row["score"]
            marker = "*" if not row["alive"] else " "
            board_lines.append(f"<white>{index}. {name:<12} {best:>5}m{marker}</white>")
        if len(board_lines) == 1:
            board_lines.append("<gray>no cars yet - type !join</gray>")
        self.hud_board.text = "\n".join(board_lines)

        speeds = [p["speed"] for p in snapshot["players"]]
        average = sum(speeds) / len(speeds) if speeds else 0.0
        state = "PAUSED" if snapshot["paused"] else f"{average:.0f} u/s"
        self.hud_status.text = (
            f"<gray>{snapshot['active_cars']}/{tuning.MAX_CARS} cars | "
            f"{state} | camera: {self.camera_mode}</gray>"
        )
        self.hud_paused.enabled = snapshot["paused"]

        if wall_clock.monotonic() < self.toast_until:
            self.hud_toast.text = self.toast
        else:
            self.hud_toast.text = ""

    # -- streamer keys -----------------------------------------------------
    def handle_input(self, key: str) -> None:
        if not self.camera_locked and key in ("f1", "1"):
            self.camera_mode = "wide"
        elif not self.camera_locked and key in ("f2", "2"):
            self.camera_mode = "leader"
        elif not self.camera_locked and key in ("f3", "3"):
            self.camera_mode = "orbit"
        elif key == "p":
            self.sim.set_paused(not self.sim.paused)
        elif key == "r":
            self.sim.reset()
            self.toast = "Race reset"
            self.toast_until = wall_clock.monotonic() + 2.5
        elif key == "escape":
            application.quit()


_view: Optional[DriveView] = None


def update() -> None:  # called by Ursina every frame
    if _view is not None:
        _view.update()


def input(key: str) -> None:  # called by Ursina
    if _view is not None:
        _view.handle_input(key)


def run(
    sim: DriveSim,
    width: int = tuning.WINDOW_WIDTH,
    height: int = tuning.WINDOW_HEIGHT,
    fullscreen: bool = False,
    event_url: Optional[str] = None,
    car_model: str = "",
    traffic_model: str = "",
    player_model_dir: str = "models/cars/players",
    model_scale: float = 0.0,
    model_yaw: float = 0.0,
    model_y_offset: float = 0.0,
    camera_mode: str = "fixed",
    camera_offset: Tuple[float, float, float] = (0.0, 32.0, -100.0),
    camera_look: Tuple[float, float, float] = (0.0, 1.0, 30.0),
) -> None:
    global _view
    app = Ursina(
        title=tuning.WINDOW_TITLE,
        size=(width, height),
        borderless=False,
        fullscreen=fullscreen,
        development_mode=False,
    )
    window.title = tuning.WINDOW_TITLE
    try:
        window.vsync = True
    except Exception:
        pass
    try:
        window.color = color.rgb32(150, 190, 230)
    except Exception:
        pass
    for attribute in ("exit_button", "fps_counter"):
        widget = getattr(window, attribute, None)
        if widget is not None:
            widget.visible = attribute == "fps_counter"

    _view = DriveView(
        sim,
        event_url=event_url,
        car_model=car_model,
        traffic_model=traffic_model,
        player_model_dir=player_model_dir,
        model_scale=model_scale,
        model_yaw=model_yaw,
        model_y_offset=model_y_offset,
        camera_mode=camera_mode,
        camera_offset=camera_offset,
        camera_look=camera_look,
    )
    app.run()
