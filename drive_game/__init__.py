"""Gem Drive - a slow-paced chat-driven 3D driving game.

The package is split so the simulation is importable without Ursina/Panda3D:

    drive_game.tuning   gameplay constants
    drive_game.sim      pure-Python simulation (headless, testable)
    drive_game.server   local HTTP API used by main.py
    drive_game.app      Ursina renderer, HUD and wide pack camera
    drive_game.__main__ entry point (args / headless mode)
"""
