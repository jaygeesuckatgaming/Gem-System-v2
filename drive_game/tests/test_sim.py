"""Unit tests for the pure-Python Gem Drive simulation.

Run from the project root (no Ursina needed):
    python -m pytest drive_game/tests -q
"""

from __future__ import annotations

import pytest

from drive_game import tuning
from drive_game.sim import DriveSim, Traffic, lane_x, normalize_command


def make_sim(**kwargs) -> DriveSim:
    kwargs.setdefault("seed", 7)
    kwargs.setdefault("car_ttl_s", 0)
    return DriveSim(**kwargs)


class TestCommands:
    def test_normalize_aliases(self):
        assert normalize_command("!LEFT") == "left"
        for short, full in (
            ("l", "left"),
            ("r", "right"),
            ("f", "faster"),
            ("s", "slower"),
            ("b", "brake"),
            ("j", "join"),
            ("q", "leave"),
            ("sc", "score"),
            ("g", "faster"),
        ):
            assert normalize_command(short) == full
        assert normalize_command("gas") == "faster"
        assert normalize_command("stop") == "brake"
        assert normalize_command("nonsense") == ""

    def test_auto_join_and_move(self):
        sim = make_sim()
        result = sim.command("alice", "left")
        assert result["accepted"] is True
        assert "alice" in sim.players
        lane_before = sim.players["alice"].lane
        sim.tick(2.0)
        result = sim.command("alice", "right")
        assert result["accepted"] is True
        assert sim.players["alice"].lane == min(tuning.LANES - 1, lane_before + 1)

    def test_unknown_command_rejected(self):
        sim = make_sim()
        result = sim.command("alice", "warp")
        assert result["accepted"] is False
        assert result["reason"] == "unknown_command"
        assert "alice" not in sim.players

    def test_lane_bounds(self):
        sim = make_sim()
        sim.command("alice", "left")
        sim.tick(1.0)
        for _ in range(5):
            sim.command("alice", "left")
            sim.tick(tuning.COMMAND_COOLDOWN_S + 0.1)
        assert sim.players["alice"].lane == 0

        for _ in range(5):
            sim.command("alice", "right")
            sim.tick(tuning.COMMAND_COOLDOWN_S + 0.1)
        assert sim.players["alice"].lane == tuning.LANES - 1

    def test_command_cooldown(self):
        sim = make_sim()
        sim.command("alice", "join")
        assert sim.command("alice", "left")["accepted"] is True
        assert sim.command("alice", "right")["reason"] == "cooldown"
        sim.tick(tuning.COMMAND_COOLDOWN_S + 0.1)
        assert sim.command("alice", "right")["accepted"] is True

    def test_join_and_score_are_free(self):
        sim = make_sim()
        sim.command("alice", "join")
        assert sim.command("alice", "score")["accepted"] is True
        assert sim.command("alice", "join")["accepted"] is True

    def test_grid_full(self):
        sim = make_sim(max_cars=2)
        sim.command("a", "join")
        sim.command("b", "join")
        result = sim.command("c", "join")
        assert result["accepted"] is False
        assert result["reason"] == "grid_full"
        assert len(sim.players) == 2

    def test_leave(self):
        sim = make_sim()
        sim.command("alice", "join")
        assert sim.command("alice", "leave")["accepted"] is True
        assert "alice" not in sim.players
        assert sim.command("alice", "leave")["accepted"] is False

    def test_global_rate_limit(self):
        sim = make_sim(max_cars=20)
        accepted = 0
        for index in range(tuning.GLOBAL_COMMANDS_PER_S + 3):
            if sim.command(f"user{index}", "left")["accepted"]:
                accepted += 1
        assert accepted == tuning.GLOBAL_COMMANDS_PER_S

    def test_paused_commands_rejected(self):
        sim = make_sim()
        sim.set_paused(True)
        result = sim.command("alice", "join")
        assert result["accepted"] is False
        assert result["reason"] == "paused"
        before = sim.now
        sim.tick(1.0)
        assert sim.now == before


class TestDriving:
    def test_tick_moves_and_scores(self):
        sim = make_sim()
        sim.command("alice", "join")
        start_z = sim.players["alice"].z
        for _ in range(30):
            sim.tick(1.0 / 30.0)
        player = sim.players["alice"]
        assert player.z > start_z
        assert player.run_score > 0

    def test_speed_commands(self):
        sim = make_sim()
        sim.command("alice", "join")
        base = sim.players["alice"].speed_target
        sim.tick(tuning.COMMAND_COOLDOWN_S + 0.1)
        sim.command("alice", "faster")
        assert sim.players["alice"].speed_target == base + tuning.SPEED_STEP
        sim.tick(tuning.COMMAND_COOLDOWN_S + 0.1)
        sim.command("alice", "slower")
        assert sim.players["alice"].speed_target == base

    def test_speed_clamped(self):
        sim = make_sim()
        sim.command("alice", "join")
        for _ in range(10):
            sim.tick(tuning.COMMAND_COOLDOWN_S + 0.1)
            sim.command("alice", "faster")
        assert sim.players["alice"].speed_target == tuning.MAX_TARGET_SPEED
        for _ in range(20):
            sim.tick(tuning.COMMAND_COOLDOWN_S + 0.1)
            sim.command("alice", "slower")
        assert sim.players["alice"].speed_target == tuning.MIN_TARGET_SPEED

    def test_brake(self):
        sim = make_sim()
        sim.command("alice", "join")
        sim.tick(1.0)
        sim.tick(tuning.COMMAND_COOLDOWN_S + 0.1)
        sim.command("alice", "brake")
        sim.tick(0.5)
        assert sim.players["alice"].speed < tuning.BASE_SPEED

    def test_crash_and_respawn(self):
        sim = make_sim()
        sim.command("alice", "join")
        player = sim.players["alice"]
        player.invuln_until = 0.0
        sim.traffic.clear()
        sim.traffic[999] = Traffic(
            id=999,
            lane=player.lane,
            z=player.z + 2.0,
            speed=0.0,
            color=(200, 90, 90),
        )
        sim.tick(0.1)
        assert player.alive is False
        assert player.crashes == 1
        assert any(e["type"] == "crash" for e in sim.drain_events())

        for _ in range(int(tuning.CRASH_RESPAWN_S / 0.25) + 4):
            sim.tick(0.25)
        assert player.alive is True
        assert player.invuln_until > sim.now

    def test_overtake_bonus(self):
        sim = make_sim()
        sim.command("alice", "join")
        player = sim.players["alice"]
        player.invuln_until = 1e9
        sim.traffic.clear()
        sim.traffic[500] = Traffic(
            id=500,
            lane=(player.lane + 1) % tuning.LANES,
            z=player.z + 1.0,
            speed=0.0,
            color=(200, 90, 90),
        )
        before = player.run_score
        sim.tick(1.0)
        assert 500 in player.passed
        assert player.run_score >= before + tuning.OVERTAKE_BONUS

    def test_ttl_expiry(self):
        sim = DriveSim(seed=1, car_ttl_s=5.0)
        sim.command("alice", "join")
        for _ in range(30):
            sim.tick(0.25)
        assert "alice" not in sim.players

    def test_traffic_spawns_and_recycles(self):
        sim = make_sim()
        sim.command("alice", "join")
        for _ in range(120):
            sim.tick(0.25)
        assert sim.traffic
        assert all(t.z > sim.players["alice"].z - 500 for t in sim.traffic.values())

    def test_no_traffic_without_players(self):
        sim = make_sim()
        for _ in range(60):
            sim.tick(0.25)
        assert not sim.traffic

    def test_first_join_spawns_nearby_traffic(self):
        sim = make_sim()
        sim.command("alice", "join")
        player = sim.players["alice"]
        assert len(sim.traffic) == len(tuning.FIRST_TRAFFIC_AHEAD)
        assert all(40.0 < t.z - player.z < 200.0 for t in sim.traffic.values())

    def test_pack_stays_compacted(self):
        sim = make_sim()
        for name in ("alice", "bob", "charlie"):
            sim.command(name, "join")
        sim.players["alice"].z = 0.0
        sim.players["bob"].z = 10.0
        sim.players["charlie"].z = 500.0
        sim.tick(0.05)
        zs = [player.z for player in sim.players.values()]
        assert max(zs) - min(zs) <= tuning.PACK_MAX_SPREAD + 1.0


class TestTrafficDensity:
    def test_default_is_sparse(self):
        sim = make_sim()
        assert sim.traffic_density == "sparse"
        assert sim.max_traffic == tuning.TRAFFIC_PRESETS["sparse"]["max_traffic"]
        sim.command("alice", "join")
        assert len(sim.traffic) == len(tuning.FIRST_TRAFFIC_AHEAD)

    def test_set_density_off_clears_traffic(self):
        sim = make_sim()
        sim.command("alice", "join")
        assert sim.traffic
        assert sim.set_traffic_density("off") is True
        assert not sim.traffic
        sim.spawn_traffic(3)
        assert not sim.traffic
        for _ in range(40):
            sim.tick(0.25)
        assert not sim.traffic

    def test_set_density_updates_cap_and_spawns(self):
        sim = make_sim()
        assert sim.set_traffic_density("dense") is True
        assert sim.max_traffic == tuning.TRAFFIC_PRESETS["dense"]["max_traffic"]
        sim.command("alice", "join")
        for _ in range(120):
            sim.tick(0.25)
        assert len(sim.traffic) <= sim.max_traffic

    def test_set_density_rejects_unknown(self):
        sim = make_sim()
        assert sim.set_traffic_density("nope") is False
        assert sim.traffic_density == "sparse"

    def test_snapshot_reports_density(self):
        sim = make_sim()
        snapshot = sim.snapshot()
        assert snapshot["traffic_density"] == "sparse"
        assert snapshot["max_traffic"] == sim.max_traffic


class TestDemo:
    def test_demo_spawns_and_drives(self):
        sim = make_sim()
        sim.set_demo(True, 3)
        assert sim.demo_enabled is True
        assert sim.demo_cars == 3
        assert len(sim.players) == 3
        assert all(player.demo for player in sim.players.values())
        start_z = {name: player.z for name, player in sim.players.items()}
        for _ in range(40):
            sim.tick(0.25)
        assert all(
            player.z > start_z[name] for name, player in sim.players.items()
        )

    def test_demo_off_removes_only_demo_cars(self):
        sim = make_sim()
        sim.command("alice", "join")
        sim.set_demo(True, 2)
        assert len(sim.players) == 3
        sim.set_demo(False)
        assert sim.demo_enabled is False
        assert list(sim.players) == ["alice"]

    def test_demo_respects_car_cap(self):
        sim = make_sim(max_cars=2)
        sim.command("alice", "join")
        sim.set_demo(True, 5)
        assert len(sim.players) <= 2
        assert sim.demo_cars <= 1

    def test_demo_reserves_slots_for_viewers(self):
        sim = make_sim(max_cars=12)
        sim.set_demo(True, 12)
        assert sim.demo_cars <= 12 - tuning.DEMO_RESERVED_SLOTS
        result = sim.command("alice", "join")
        assert result["accepted"] is True
        assert "alice" in sim.players

    def test_real_join_evicts_demo_when_full(self):
        sim = make_sim(max_cars=12, demo_reserved_slots=0)
        sim.set_demo(True, 12)
        assert len(sim.players) == 12
        assert all(player.demo for player in sim.players.values())
        result = sim.command("alice", "join")
        assert result["accepted"] is True
        assert "alice" in sim.players
        assert not sim.players["alice"].demo
        assert len(sim.players) == 12
        assert sum(1 for player in sim.players.values() if player.demo) == 11

    def test_demo_cars_ignore_ttl(self):
        sim = DriveSim(seed=3, car_ttl_s=5.0)
        sim.set_demo(True, 2)
        for _ in range(80):
            sim.tick(0.25)
        assert sim.demo_enabled is True
        assert len(sim.players) == 2

    def test_reset_keeps_demo_mode(self):
        sim = make_sim()
        sim.set_demo(True, 2)
        sim.reset()
        assert sim.demo_enabled is True
        assert len(sim.players) == 2

    def test_demo_events_are_flagged(self):
        sim = make_sim()
        sim.set_demo(True, 1)
        assert sim.force_crash("Demo 1") is True
        crash = next(e for e in sim.drain_events() if e["type"] == "crash")
        assert crash["demo"] is True


class TestViews:
    def test_snapshot_shape(self):
        sim = make_sim()
        sim.command("alice", "join")
        sim.tick(1.0)
        snapshot = sim.snapshot()
        assert snapshot["active_cars"] == 1
        assert snapshot["players"][0]["user"] == "alice"
        assert "pack" in snapshot
        assert snapshot["leaderboard"][0]["user"] == "alice"

    def test_leaderboard_order(self):
        sim = make_sim()
        sim.command("alice", "join")
        sim.command("bob", "join")
        sim.players["alice"].best_score = 100
        sim.players["bob"].best_score = 250
        board = sim.leaderboard()
        assert [row["user"] for row in board] == ["bob", "alice"]

    def test_leaderboard_excludes_demo_cars(self):
        sim = make_sim()
        sim.set_demo(True, 3)
        assert sim.leaderboard() == []
        result = sim.command("alice", "join")
        assert result["accepted"] is True
        board = sim.leaderboard()
        assert [row["user"] for row in board] == ["alice"]

    def test_pack_extent(self):
        sim = make_sim()
        sim.command("alice", "join")
        sim.command("bob", "join")
        sim.players["alice"].z = 10
        sim.players["bob"].z = 50
        pack = sim.snapshot()["pack"]
        assert pack["min_z"] == 10
        assert pack["max_z"] == 50
        assert pack["center_z"] == 30

    def test_reset(self):
        sim = make_sim()
        sim.command("alice", "join")
        sim.reset()
        assert not sim.players
        assert not sim.traffic
        assert any(e["type"] == "session_start" for e in sim.drain_events())

    def test_force_crash(self):
        sim = make_sim()
        assert sim.force_crash("nobody") is False
        sim.command("alice", "join")
        assert sim.force_crash("alice") is True
        assert sim.players["alice"].alive is False

    def test_lane_x_centered(self):
        positions = [lane_x(lane) for lane in range(tuning.LANES)]
        assert positions == sorted(positions)
        assert abs(sum(positions)) < 1e-9
