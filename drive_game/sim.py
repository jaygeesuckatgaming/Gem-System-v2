"""Pure-Python simulation for Gem Drive.

No Ursina/Panda3D imports live here, so the whole game can be ticked headless
in tests (`python -m drive_game --headless`). The HTTP server and the Ursina
renderer share one DriveSim; all public methods take a re-entrant lock so the
server thread and the render thread can call them safely.

Coordinate system: +Z is down the road (distance travelled), +X is across the
lanes. Cars are lane-based - commands shift a car one lane at a time instead of
steering continuously, which keeps chat input slow and readable.
"""

from __future__ import annotations

import random
import threading
import zlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import tuning

COLORS: Tuple[Tuple[int, int, int], ...] = (
    (235, 87, 87),
    (242, 153, 74),
    (242, 201, 76),
    (111, 207, 151),
    (86, 204, 242),
    (86, 130, 242),
    (155, 120, 242),
    (242, 120, 190),
    (224, 224, 224),
    (130, 220, 200),
)


def normalize_command(command: str) -> str:
    """Lowercase and expand a command alias. Returns '' for unknown input."""
    command = (command or "").strip().lower().lstrip("!")
    command = tuning.ALIASES.get(command, command)
    return command if command in tuning.COMMANDS else ""


def lane_x(lane: int) -> float:
    """World X coordinate of a lane centre."""
    lane = max(0, min(tuning.LANES - 1, lane))
    return (lane - (tuning.LANES - 1) / 2.0) * tuning.LANE_WIDTH


def car_color(user: str) -> Tuple[int, int, int]:
    """Stable colour for a viewer across restarts."""
    return COLORS[zlib.crc32(user.encode("utf-8")) % len(COLORS)]


@dataclass
class Player:
    user: str
    lane: int
    x: float
    z: float
    speed: float
    speed_target: float
    color: Tuple[int, int, int]
    run_score: float = 0.0
    best_score: float = 0.0
    alive: bool = True
    crashes: int = 0
    respawn_at: float = 0.0
    invuln_until: float = 0.0
    brake_until: float = 0.0
    last_command_at: float = 0.0
    last_seen_at: float = 0.0
    demo: bool = False
    next_milestone: float = tuning.MILESTONE_STEP
    passed: set = field(default_factory=set)


@dataclass
class Traffic:
    id: int
    lane: int
    z: float
    speed: float
    color: Tuple[int, int, int]


class DriveSim:
    """The whole game state and its rules."""

    def __init__(
        self,
        seed: Optional[int] = None,
        max_cars: int = tuning.MAX_CARS,
        car_ttl_s: float = tuning.CAR_TTL_S,
        command_cooldown_s: float = tuning.COMMAND_COOLDOWN_S,
        traffic_density: str = tuning.DEFAULT_TRAFFIC_DENSITY,
        demo_reserved_slots: int = tuning.DEMO_RESERVED_SLOTS,
    ) -> None:
        self.lock = threading.RLock()
        self.rng = random.Random(seed)
        self.max_cars = int(max_cars)
        self.demo_reserved_slots = max(0, int(demo_reserved_slots))
        self.car_ttl_s = float(car_ttl_s)
        self.command_cooldown_s = float(command_cooldown_s)
        self.traffic_density = (
            traffic_density
            if traffic_density in tuning.TRAFFIC_PRESETS
            else tuning.DEFAULT_TRAFFIC_DENSITY
        )
        preset = tuning.TRAFFIC_PRESETS[self.traffic_density]
        self.max_traffic = int(preset["max_traffic"])
        self.traffic_spawn_min_s = float(preset["spawn_min_s"])
        self.traffic_spawn_max_s = float(preset["spawn_max_s"])
        self.first_traffic_ahead = tuple(preset["first_ahead"])
        self.players: Dict[str, Player] = {}
        self.traffic: Dict[int, Traffic] = {}
        self.events: List[Dict[str, Any]] = []
        self.now = 0.0
        self.tick_count = 0
        self.paused = False
        self._next_traffic_id = 1
        self._traffic_timer = 0.0
        self._command_times: List[float] = []
        self._leader: Optional[str] = None
        self._leader_event_at = -1e9
        self.demo_enabled = False
        self.demo_cars = 0
        self._demo_next: Dict[str, float] = {}

    # -- commands -----------------------------------------------------------
    def command(self, user: str, command: str) -> Dict[str, Any]:
        """Apply a chat command. Returns an API-friendly result dict."""
        user = (user or "viewer").strip()[:24] or "viewer"
        cmd = normalize_command(command)
        with self.lock:
            if not cmd:
                return self._result(False, "unknown_command", user, command)
            if self.paused:
                return self._result(False, "paused", user, cmd)

            if cmd == "leave":
                existed = self.players.pop(user, None) is not None
                return self._result(existed, "left" if existed else "not_driving", user, cmd)

            player = self.players.get(user)
            if player is None:
                if len(self.players) >= self.max_cars:
                    # Demo cars must give way to real viewers.
                    if not self._evict_demo_for_viewer():
                        return self._result(False, "grid_full", user, cmd)
                player = self._spawn_player(user)

            # Movement commands are rate limited; join/score are free.
            if cmd not in ("join", "score"):
                if self.now - player.last_command_at + 1e-9 < self.command_cooldown_s:
                    return self._result(False, "cooldown", user, cmd, player)
                if not self._take_global_command_slot():
                    return self._result(False, "rate_limited", user, cmd, player)

            if cmd not in ("join", "score"):
                player.last_command_at = self.now
            player.last_seen_at = self.now

            if cmd == "left":
                player.lane = max(0, player.lane - 1)
            elif cmd == "right":
                player.lane = min(tuning.LANES - 1, player.lane + 1)
            elif cmd == "faster":
                player.speed_target = min(
                    tuning.MAX_TARGET_SPEED, player.speed_target + tuning.SPEED_STEP
                )
            elif cmd == "slower":
                player.speed_target = max(
                    tuning.MIN_TARGET_SPEED, player.speed_target - tuning.SPEED_STEP
                )
            elif cmd == "brake":
                player.brake_until = self.now + tuning.BRAKE_DURATION_S
            elif cmd == "join":
                pass

            return self._result(True, "ok", user, cmd, player)

    def _take_global_command_slot(self) -> bool:
        cutoff = self.now - 1.0
        self._command_times = [t for t in self._command_times if t >= cutoff]
        if len(self._command_times) >= tuning.GLOBAL_COMMANDS_PER_S:
            return False
        self._command_times.append(self.now)
        return True

    def _spawn_player(self, user: str, demo: bool = False) -> Player:
        first_player = not self.players
        # Spawn at the back of the pack so the new car enters at the bottom of
        # the fixed camera's view (near the camera), then drives forward.
        pack_z = self._pack_min_z()
        lane = self.rng.randrange(tuning.LANES)
        player = Player(
            user=user,
            lane=lane,
            x=lane_x(lane),
            z=pack_z - self.rng.uniform(0.0, 6.0),
            speed=tuning.BASE_SPEED,
            speed_target=tuning.BASE_SPEED,
            color=car_color(user),
            last_command_at=self.now - self.command_cooldown_s,
            last_seen_at=self.now,
            demo=demo,
        )
        self.players[user] = player
        if first_player:
            # The road was empty while the stream waited for viewers; start
            # fresh with a few cars close enough to see.
            self.traffic.clear()
            self._traffic_timer = 0.0
            for ahead in self.first_traffic_ahead:
                self._spawn_traffic(ahead=ahead)
        return player

    # -- simulation ---------------------------------------------------------
    def tick(self, dt: float) -> None:
        """Advance the world. Call at render rate (dt is clamped to 0.25s)."""
        with self.lock:
            if self.paused:
                return
            remaining = max(0.0, min(5.0, float(dt)))
            if remaining <= 0.0:
                return
            # Sub-step so a long frame (or a test's big tick) cannot skip
            # collisions, cooldowns or respawns.
            while remaining > 0.0:
                step = min(0.05, remaining)
                self._step(step)
                remaining -= step

    def _step(self, dt: float) -> None:
        self.now += dt
        self.tick_count += 1

        self._expire_players()
        self._update_demo(dt)
        self._update_players(dt)
        self._update_traffic(dt)
        self._detect_collisions()
        self._check_leader()

    def _expire_players(self) -> None:
        if self.car_ttl_s <= 0:
            return
        expired = [
            user
            for user, p in self.players.items()
            if self.now - p.last_seen_at > self.car_ttl_s
        ]
        for user in expired:
            del self.players[user]

    def _update_demo(self, dt: float) -> None:
        """Auto-drive demo cars so settings can be tested without chat."""
        if not self.demo_enabled:
            return
        for user, player in list(self.players.items()):
            if not player.demo:
                continue
            player.last_seen_at = self.now
            if not player.alive:
                continue

            due = self._demo_next.get(user)
            if due is None:
                due = self.now + self.rng.uniform(0.5, 1.5)
                self._demo_next[user] = due
            if self.now < due:
                continue

            interval = max(
                self.command_cooldown_s + 0.3, self.rng.uniform(1.6, 3.2)
            )
            self._demo_next[user] = self.now + interval

            options = []
            if player.lane > 0:
                options.extend(("left", "left"))
            if player.lane < tuning.LANES - 1:
                options.extend(("right", "right"))
            options.extend(("faster", "slower", "brake"))
            self.command(user, self.rng.choice(options))

    def _update_players(self, dt: float) -> None:
        alive = [p for p in self.players.values() if p.alive]
        median_z = self._median([p.z for p in alive]) if alive else 0.0

        for player in list(self.players.values()):
            if not player.alive:
                if self.now >= player.respawn_at:
                    self._respawn(player)
                continue

            # Slide toward the target lane instead of snapping.
            target_x = lane_x(player.lane)
            max_dx = tuning.LANE_WIDTH / tuning.LANE_CHANGE_TIME * dt
            player.x += max(-max_dx, min(max_dx, target_x - player.x))

            target_speed = (
                tuning.BRAKE_SPEED
                if self.now < player.brake_until
                else player.speed_target
            )
            if player.z < median_z - tuning.RUBBER_BAND_DISTANCE:
                target_speed *= tuning.RUBBER_BAND_BOOST
            elif player.z > median_z + tuning.RUBBER_BAND_DISTANCE:
                target_speed *= tuning.RUBBER_BAND_SLOW

            player.speed = self._approach(player.speed, target_speed, tuning.ACCEL * dt)

            # Rear car auto-brakes behind another player instead of crashing.
            for other in alive:
                if other is player or other.lane != player.lane:
                    continue
                gap = other.z - player.z
                if 0.0 < gap < tuning.SAFE_GAP:
                    player.speed = min(player.speed, max(0.0, other.speed - 0.5))

            previous_z = player.z
            player.z += player.speed * dt
            player.run_score += player.speed * dt

            self._award_overtakes(player, previous_z)
            self._award_milestones(player)

        self._compact_pack()

    def _compact_pack(self) -> None:
        """Hold leading cars so the pack never spreads beyond PACK_MAX_SPREAD.

        This keeps every car within the fixed camera's frame instead of letting
        the leaders shrink to dots far ahead.
        """
        alive = [p for p in self.players.values() if p.alive]
        if len(alive) < 2:
            return
        pack_min = min(player.z for player in alive)
        front_limit = pack_min + tuning.PACK_MAX_SPREAD
        for player in alive:
            if player.z > front_limit:
                player.z = front_limit
                player.speed = 0.0

    def _respawn(self, player: Player) -> None:
        player.alive = True
        player.z = self._pack_median_z()
        player.x = lane_x(player.lane)
        player.speed = tuning.BASE_SPEED
        player.speed_target = tuning.BASE_SPEED
        player.run_score = 0.0
        player.next_milestone = tuning.MILESTONE_STEP
        player.invuln_until = self.now + tuning.INVULN_S
        player.passed.clear()

    def _update_traffic(self, dt: float) -> None:
        if not self.players:
            # Empty road while the stream waits for the first viewer.
            self.traffic.clear()
            self._traffic_timer = 0.0
            return

        for traffic in list(self.traffic.values()):
            traffic.z += traffic.speed * dt

        pack_min = self._pack_extent()[0]
        for traffic_id, traffic in list(self.traffic.items()):
            if traffic.z < pack_min - tuning.TRAFFIC_DESPAWN_BEHIND:
                del self.traffic[traffic_id]

        self._traffic_timer -= dt
        if self._traffic_timer <= 0.0:
            if self.max_traffic <= 0:
                return
            self._traffic_timer = self.rng.uniform(
                self.traffic_spawn_min_s, self.traffic_spawn_max_s
            )
            if len(self.traffic) < self.max_traffic:
                self._spawn_traffic()

    def _spawn_traffic(self, ahead: Optional[float] = None) -> Traffic:
        pack_max = self._pack_extent()[1]
        if ahead is None:
            ahead = self.rng.uniform(
                tuning.TRAFFIC_SPAWN_AHEAD_MIN, tuning.TRAFFIC_SPAWN_AHEAD_MAX
            )
        traffic = Traffic(
            id=self._next_traffic_id,
            lane=self.rng.randrange(tuning.LANES),
            z=pack_max + ahead,
            speed=self.rng.uniform(tuning.TRAFFIC_SPEED_MIN, tuning.TRAFFIC_SPEED_MAX),
            color=(210, 90, 90),
        )
        self._next_traffic_id += 1
        self.traffic[traffic.id] = traffic
        return traffic

    def _detect_collisions(self) -> None:
        for player in list(self.players.values()):
            if not player.alive or self.now < player.invuln_until:
                continue
            for traffic in self.traffic.values():
                if traffic.lane != player.lane:
                    continue
                if abs(player.z - traffic.z) < tuning.COLLISION_GAP:
                    self._crash(player, "traffic")
                    break

    def _crash(self, player: Player, cause: str) -> None:
        player.alive = False
        player.crashes += 1
        player.best_score = max(player.best_score, player.run_score)
        player.run_score = 0.0
        player.speed = 0.0
        player.speed_target = tuning.BASE_SPEED
        player.respawn_at = self.now + tuning.CRASH_RESPAWN_S
        player.next_milestone = tuning.MILESTONE_STEP
        self._emit(
            "crash",
            user=player.user,
            score=round(player.best_score),
            crashes=player.crashes,
            cause=cause,
            demo=player.demo,
        )

    def _award_overtakes(self, player: Player, previous_z: float) -> None:
        for traffic in self.traffic.values():
            if traffic.id in player.passed:
                continue
            if previous_z < traffic.z <= player.z:
                player.passed.add(traffic.id)
                player.run_score += tuning.OVERTAKE_BONUS

    def _award_milestones(self, player: Player) -> None:
        while player.run_score >= player.next_milestone:
            self._emit(
                "milestone",
                user=player.user,
                score=round(player.next_milestone),
                demo=player.demo,
            )
            player.next_milestone += tuning.MILESTONE_STEP

    def _check_leader(self) -> None:
        top = self._leaderboard_rows(limit=1)
        if not top:
            return
        leader = top[0]["user"]
        score = top[0]["best"] or top[0]["score"]
        if score <= 0 or leader == self._leader:
            return
        # Debounce: with a pack of cars the lead changes constantly. Only
        # announce a new leader at most once every LEADER_EVENT_COOLDOWN_S.
        if self.now - self._leader_event_at < tuning.LEADER_EVENT_COOLDOWN_S:
            return
        self._leader = leader
        self._leader_event_at = self.now
        self._emit("leader", user=leader, score=score, demo=top[0]["demo"])

    # -- views --------------------------------------------------------------
    def leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self._leaderboard_rows(limit=limit)

    def _leaderboard_rows(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self.lock:
            rows = [
                {
                    "user": p.user,
                    "best": round(p.best_score),
                    "score": round(p.run_score),
                    "alive": p.alive,
                    "crashes": p.crashes,
                    "demo": p.demo,
                }
                for p in self.players.values()
                if not p.demo
            ]
        rows.sort(
            key=lambda row: (row["best"], row["score"], row["user"]), reverse=True
        )
        return rows[:limit]

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            pack_min, pack_max, pack_center = self._pack_extent()
            return {
                "now": round(self.now, 2),
                "tick": self.tick_count,
                "paused": self.paused,
                "active_cars": len(self.players),
                "demo_enabled": self.demo_enabled,
                "demo_cars": self.demo_cars,
                "traffic_density": self.traffic_density,
                "max_traffic": self.max_traffic,
                "players": [
                    {
                        "user": p.user,
                        "lane": p.lane,
                        "x": round(p.x, 3),
                        "z": round(p.z, 3),
                        "speed": round(p.speed, 2),
                        "score": round(p.run_score),
                        "best": round(p.best_score),
                        "alive": p.alive,
                        "crashes": p.crashes,
                        "demo": p.demo,
                        "color": list(p.color),
                    }
                    for p in self.players.values()
                ],
                "traffic": [
                    {
                        "id": t.id,
                        "lane": t.lane,
                        "z": round(t.z, 3),
                        "speed": round(t.speed, 2),
                        "color": list(t.color),
                    }
                    for t in self.traffic.values()
                ],
                "leaderboard": self.leaderboard(limit=10),
                "pack": {
                    "min_z": round(pack_min, 2),
                    "max_z": round(pack_max, 2),
                    "center_z": round(pack_center, 2),
                },
            }

    def drain_events(self) -> List[Dict[str, Any]]:
        with self.lock:
            events, self.events = self.events, []
            return events

    # -- streamer controls --------------------------------------------------
    def set_paused(self, paused: bool) -> None:
        with self.lock:
            self.paused = bool(paused)

    def set_traffic_density(self, density: str) -> bool:
        """Switch traffic preset live (off / sparse / normal / dense)."""
        key = str(density or "").strip().lower()
        with self.lock:
            preset = tuning.TRAFFIC_PRESETS.get(key)
            if preset is None:
                return False
            self.traffic_density = key
            self.max_traffic = int(preset["max_traffic"])
            self.traffic_spawn_min_s = float(preset["spawn_min_s"])
            self.traffic_spawn_max_s = float(preset["spawn_max_s"])
            self.first_traffic_ahead = tuple(preset["first_ahead"])
            self._traffic_timer = 0.0
            if self.max_traffic <= 0:
                self.traffic.clear()
            elif len(self.traffic) > self.max_traffic:
                center = self._pack_extent()[2]
                keep = sorted(
                    self.traffic.values(), key=lambda t: abs(t.z - center)
                )[: self.max_traffic]
                self.traffic = {traffic.id: traffic for traffic in keep}
            return True

    def _evict_demo_for_viewer(self) -> bool:
        """Remove the least-recently-active demo car to make room for a viewer."""
        demo_users = [user for user, player in self.players.items() if player.demo]
        if not demo_users:
            return False
        victim = min(demo_users, key=lambda user: self.players[user].last_seen_at)
        del self.players[victim]
        self._demo_next.pop(victim, None)
        self.demo_cars = sum(1 for player in self.players.values() if player.demo)
        self.demo_enabled = self.demo_cars > 0
        return True

    def set_demo(self, enabled: bool, cars: int = 6) -> None:
        """Toggle synthetic auto-driving cars for testing without chat."""
        with self.lock:
            enabled = bool(enabled)
            demo_limit = max(0, self.max_cars - self.demo_reserved_slots)
            requested = max(0, min(int(cars), demo_limit))

            if not enabled:
                for user in [u for u, p in self.players.items() if p.demo]:
                    del self.players[user]
                self._demo_next.clear()
                self.demo_enabled = False
                self.demo_cars = 0
                return

            targets = [f"Demo {index}" for index in range(1, requested + 1)]
            for user in [
                u for u, p in self.players.items() if p.demo and u not in targets
            ]:
                del self.players[user]
                self._demo_next.pop(user, None)

            for user in targets:
                existing = self.players.get(user)
                if existing is not None and not existing.demo:
                    continue
                if existing is None:
                    if len(self.players) >= self.max_cars:
                        break
                    self._spawn_player(user, demo=True)
                self._demo_next.setdefault(
                    user, self.now + self.rng.uniform(0.3, 1.2)
                )

            self.demo_cars = sum(1 for p in self.players.values() if p.demo)
            self.demo_enabled = self.demo_cars > 0

    def reset(self) -> None:
        with self.lock:
            demo_enabled = self.demo_enabled
            demo_cars = self.demo_cars
            self.players.clear()
            self.traffic.clear()
            self._leader = None
            self._leader_event_at = -1e9
            self._traffic_timer = 0.0
            self._demo_next.clear()
            self.demo_enabled = False
            self.demo_cars = 0
            self._emit("session_start", users=0)
            if demo_enabled and demo_cars:
                self.set_demo(True, demo_cars)

    def spawn_traffic(self, count: int = 1, ahead: float = 120.0) -> None:
        with self.lock:
            available = max(0, self.max_traffic - len(self.traffic))
            for _ in range(min(max(0, int(count)), available)):
                self._spawn_traffic(ahead=ahead)

    def force_crash(self, user: str) -> bool:
        with self.lock:
            player = self.players.get((user or "").strip()[:24])
            if player is None or not player.alive:
                return False
            self._crash(player, "debug")
            return True

    # -- helpers ------------------------------------------------------------
    def _emit(self, event_type: str, **data: Any) -> None:
        self.events.append({"type": event_type, "ts": round(self.now, 2), **data})
        if len(self.events) > 200:
            del self.events[:-200]

    def _pack_extent(self) -> Tuple[float, float, float]:
        zs = [p.z for p in self.players.values()]
        if not zs:
            return 0.0, 0.0, 0.0
        minimum, maximum = min(zs), max(zs)
        return minimum, maximum, (minimum + maximum) / 2.0

    def _pack_median_z(self) -> float:
        return self._median([p.z for p in self.players.values()])

    def _pack_min_z(self) -> float:
        alive = [p.z for p in self.players.values() if p.alive]
        return min(alive) if alive else 0.0

    @staticmethod
    def _median(values: List[float]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2.0

    @staticmethod
    def _approach(value: float, target: float, max_delta: float) -> float:
        if value < target:
            return min(target, value + max_delta)
        return max(target, value - max_delta)

    @staticmethod
    def _result(
        accepted: bool,
        reason: str,
        user: str,
        command: str,
        player: Optional[Player] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "accepted": accepted,
            "reason": reason,
            "user": user,
            "command": command,
        }
        if player is not None:
            result.update(
                {
                    "lane": player.lane,
                    "speed": round(player.speed, 2),
                    "speed_target": round(player.speed_target, 2),
                    "score": round(player.run_score),
                    "best": round(player.best_score),
                    "alive": player.alive,
                }
            )
        return result
