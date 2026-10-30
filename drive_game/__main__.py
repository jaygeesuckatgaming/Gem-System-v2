"""Entry point for Gem Drive.

Examples:
    python -m drive_game                        # windowed game + local API
    python -m drive_game --headless --ticks 900 # simulation only (tests/CI)
    python -m drive_game --no-server            # window only, no HTTP API
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from . import tuning
from .sim import DriveSim


def _load_config() -> Optional[Any]:
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        import config  # type: ignore

        return config
    except Exception as exc:  # pragma: no cover - config is optional for headless
        print(f"[GAME] config.py not loaded ({exc}); using defaults", flush=True)
        return None


def _parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gem Drive - chat-driven 3D highway")
    parser.add_argument("--host", default=None, help="API bind host (default: config)")
    parser.add_argument("--port", type=int, default=None, help="API port (default: config)")
    parser.add_argument("--headless", action="store_true", help="run the simulation without Ursina")
    parser.add_argument("--ticks", type=int, default=900, help="headless ticks to run")
    parser.add_argument("--seed", type=int, default=None, help="deterministic RNG seed")
    parser.add_argument("--players", type=int, default=6, help="headless: synthetic cars to join")
    parser.add_argument("--demo", action="store_true", help="auto-drive demo cars (no chat needed)")
    parser.add_argument(
        "--traffic-density",
        choices=sorted(tuning.TRAFFIC_PRESETS),
        default=None,
        help="off / sparse / normal / dense (default: config)",
    )
    parser.add_argument("--demo-cars", type=int, default=6, help="number of demo cars")
    parser.add_argument("--width", type=int, default=tuning.WINDOW_WIDTH)
    parser.add_argument("--height", type=int, default=tuning.WINDOW_HEIGHT)
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--no-server", action="store_true", help="do not start the HTTP API")
    parser.add_argument("--event-url", default=None, help="main.py commentary endpoint")
    return parser.parse_args(argv)


def _run_headless(sim: DriveSim, ticks: int, players: int, seed: Optional[int]) -> None:
    rng = random.Random(seed)
    names = [f"viewer{index}" for index in range(max(0, players))]
    for name in names:
        sim.command(name, "join")

    commands = ["left", "right", "faster", "slower", "brake"]
    for tick in range(max(0, ticks)):
        if names and tick % 45 == 0:
            sim.command(rng.choice(names), rng.choice(commands))
        sim.tick(1.0 / 30.0)

    snapshot = sim.snapshot()
    summary: Dict[str, Any] = {
        "ticks": snapshot["tick"],
        "sim_time_s": snapshot["now"],
        "active_cars": snapshot["active_cars"],
        "traffic": len(snapshot["traffic"]),
        "leaderboard": snapshot["leaderboard"][:5],
        "pack": snapshot["pack"],
        "events": sim.drain_events()[-8:],
    }
    print(json.dumps(summary, indent=2))


def _run_windowed(
    sim: DriveSim,
    args: argparse.Namespace,
    event_url: Optional[str],
    model_settings: Optional[dict] = None,
    camera_settings: Optional[dict] = None,
) -> None:
    from .app import run as run_app

    settings = model_settings or {}
    camera = camera_settings or {}
    run_app(
        sim,
        width=args.width,
        height=args.height,
        fullscreen=args.fullscreen,
        event_url=event_url,
        car_model=settings.get("car_model", ""),
        traffic_model=settings.get("traffic_model", ""),
        player_model_dir=settings.get("player_model_dir", "models/cars/players"),
        model_scale=settings.get("model_scale", 0.0),
        model_yaw=settings.get("model_yaw", 0.0),
        model_y_offset=settings.get("model_y_offset", 0.0),
        camera_mode=camera.get("mode", "fixed"),
        camera_offset=camera.get("offset", (0.0, 32.0, -100.0)),
        camera_look=camera.get("look", (0.0, 1.0, 30.0)),
    )


def main(argv: Optional[list] = None) -> int:
    args = _parse_args(argv)
    cfg = _load_config()

    host = args.host or getattr(cfg, "GAME_DRIVE_HOST", "127.0.0.1")
    port = args.port or int(getattr(cfg, "GAME_DRIVE_PORT", 5010))
    event_url = args.event_url or getattr(
        cfg, "GAME_DRIVE_EVENT_URL", "http://127.0.0.1:5000/api/game/event"
    )
    max_cars = int(getattr(cfg, "GAME_DRIVE_MAX_CARS", tuning.MAX_CARS))
    demo_reserved_slots = int(
        getattr(cfg, "GAME_DRIVE_DEMO_RESERVED_SLOTS", tuning.DEMO_RESERVED_SLOTS)
    )
    ttl = float(getattr(cfg, "GAME_DRIVE_CAR_TTL_S", tuning.CAR_TTL_S))
    cooldown = float(
        getattr(cfg, "GAME_DRIVE_COMMAND_COOLDOWN_S", tuning.COMMAND_COOLDOWN_S)
    )
    traffic_density = (
        args.traffic_density
        or getattr(cfg, "GAME_DRIVE_TRAFFIC_DENSITY", tuning.DEFAULT_TRAFFIC_DENSITY)
    )
    camera_settings = {
        "mode": getattr(cfg, "GAME_DRIVE_CAMERA_MODE", "fixed"),
        "offset": (
            float(getattr(cfg, "GAME_DRIVE_CAMERA_OFFSET_X", 0.0) or 0.0),
            float(getattr(cfg, "GAME_DRIVE_CAMERA_OFFSET_Y", 32.0) or 0.0),
            float(getattr(cfg, "GAME_DRIVE_CAMERA_OFFSET_Z", -100.0) or 0.0),
        ),
        "look": (
            float(getattr(cfg, "GAME_DRIVE_CAMERA_LOOK_X", 0.0) or 0.0),
            float(getattr(cfg, "GAME_DRIVE_CAMERA_LOOK_Y", 1.0) or 0.0),
            float(getattr(cfg, "GAME_DRIVE_CAMERA_LOOK_Z", 30.0) or 0.0),
        ),
    }
    model_settings = {
        "car_model": getattr(cfg, "GAME_DRIVE_CAR_MODEL", ""),
        "traffic_model": getattr(cfg, "GAME_DRIVE_TRAFFIC_MODEL", ""),
        "player_model_dir": getattr(cfg, "GAME_DRIVE_PLAYER_MODEL_DIR", "models/cars/players"),
        "model_scale": float(getattr(cfg, "GAME_DRIVE_MODEL_SCALE", 0.0) or 0.0),
        "model_yaw": float(getattr(cfg, "GAME_DRIVE_MODEL_YAW", 0.0) or 0.0),
        "model_y_offset": float(getattr(cfg, "GAME_DRIVE_MODEL_Y_OFFSET", 0.0) or 0.0),
    }

    sim = DriveSim(
        seed=args.seed,
        max_cars=max_cars,
        car_ttl_s=ttl,
        command_cooldown_s=cooldown,
        traffic_density=traffic_density,
        demo_reserved_slots=demo_reserved_slots,
    )

    if args.demo:
        sim.set_demo(True, args.demo_cars)

    if args.headless:
        _run_headless(sim, args.ticks, args.players, args.seed)
        return 0

    if not args.no_server:
        from .server import start_server

        start_server(sim, host=host, port=port)

    print("=" * 64, flush=True)
    print("Gem Drive - chat highway", flush=True)
    print(f"  API:     http://{host}:{port}/api/state", flush=True)
    print(f"  Events:  {event_url}", flush=True)
    print(f"  Commands: {', '.join('!' + c for c in tuning.COMMANDS)}", flush=True)
    print(f"  Traffic:  {sim.traffic_density} (max {sim.max_traffic})", flush=True)
    print(f"  Camera:   {camera_settings['mode']} {camera_settings['offset']}", flush=True)
    if args.demo:
        print(f"  Demo:     {args.demo_cars} auto-driving cars", flush=True)
    print("=" * 64, flush=True)

    try:
        _run_windowed(sim, args, event_url, model_settings, camera_settings)
    except KeyboardInterrupt:
        print("\n[GAME] stopped", flush=True)
    return 0


def update() -> None:
    """Ursina only calls update() from the __main__ module."""
    from . import app as game_app

    game_app.update()


def input(key: str) -> None:
    """Ursina likewise dispatches keyboard input via __main__.input."""
    from . import app as game_app

    game_app.input(key)


if __name__ == "__main__":
    raise SystemExit(main())
