"""Gameplay tuning for Gem Drive.

Everything here is deliberately slow and forgiving: cars cruise instead of
racing, lane changes are the main input, and traffic is easy to read on a
stream. Change these values to retune the whole game.
"""

# Road -----------------------------------------------------------------------
LANES = 4
LANE_WIDTH = 3.6
ROAD_WIDTH = LANES * LANE_WIDTH

# Player cars ----------------------------------------------------------------
BASE_SPEED = 12.0            # units/second (~43 km/h): slow cruise
MIN_TARGET_SPEED = 6.0
MAX_TARGET_SPEED = 22.0
SPEED_STEP = 3.0             # !faster / !slower change
ACCEL = 4.5                  # units/second^2 toward the target speed
BRAKE_SPEED = 3.0
BRAKE_DURATION_S = 3.0
LANE_CHANGE_TIME = 0.55      # seconds to slide into the next lane

CAR_LENGTH = 4.2
CAR_WIDTH = 1.8
SAFE_GAP = 8.0               # player-player auto-brake distance
COLLISION_GAP = 3.4          # player-traffic crash distance

CRASH_RESPAWN_S = 5.0
INVULN_S = 2.5

# Chat / roster --------------------------------------------------------------
MAX_CARS = 12
DEMO_RESERVED_SLOTS = 2      # keep this many slots free for real viewers
CAR_TTL_S = 180.0            # no command for this long -> car leaves
COMMAND_COOLDOWN_S = 2.0     # per viewer
GLOBAL_COMMANDS_PER_S = 12   # protects the sim from command floods

COMMANDS = ("left", "right", "faster", "slower", "brake", "join", "leave", "score")
ALIASES = {
    "l": "left",
    "r": "right",
    "f": "faster",
    "s": "slower",
    "b": "brake",
    "j": "join",
    "q": "leave",
    "sc": "score",
    "g": "faster",
    "gas": "faster",
    "accelerate": "faster",
    "speedup": "faster",
    "slow": "slower",
    "stop": "brake",
    "quit": "leave",
    "stats": "score",
    "leaderboard": "score",
}

# Traffic --------------------------------------------------------------------
# Sparse is the default: a stream delay makes dense traffic frustrating.
MAX_TRAFFIC = 5
TRAFFIC_SPEED_MIN = 4.0
TRAFFIC_SPEED_MAX = 8.0
TRAFFIC_SPAWN_MIN_S = 4.0
TRAFFIC_SPAWN_MAX_S = 7.0
# Spawn traffic inside the fixed camera's frame (not hundreds of units ahead,
# where it would be invisible).
TRAFFIC_SPAWN_AHEAD_MIN = 40.0
TRAFFIC_SPAWN_AHEAD_MAX = 110.0
TRAFFIC_DESPAWN_BEHIND = 80.0

# Cars placed when the first viewer joins (so the road isn't empty).
FIRST_TRAFFIC_AHEAD = (50.0, 90.0)

DEFAULT_TRAFFIC_DENSITY = "sparse"

# Selectable in the Games tab (GAME_DRIVE_TRAFFIC_DENSITY).
TRAFFIC_PRESETS = {
    "off": {
        "max_traffic": 0,
        "spawn_min_s": 0.0,
        "spawn_max_s": 0.0,
        "first_ahead": (),
    },
    "sparse": {
        "max_traffic": MAX_TRAFFIC,
        "spawn_min_s": TRAFFIC_SPAWN_MIN_S,
        "spawn_max_s": TRAFFIC_SPAWN_MAX_S,
        "first_ahead": FIRST_TRAFFIC_AHEAD,
    },
    "normal": {
        "max_traffic": 10,
        "spawn_min_s": 2.5,
        "spawn_max_s": 4.5,
        "first_ahead": (50.0, 80.0, 110.0),
    },
    "dense": {
        "max_traffic": 14,
        "spawn_min_s": 1.5,
        "spawn_max_s": 3.0,
        "first_ahead": (40.0, 70.0, 100.0),
    },
}

# Leader announcements -------------------------------------------------------
LEADER_EVENT_COOLDOWN_S = 15.0

# Scoring --------------------------------------------------------------------
OVERTAKE_BONUS = 20.0
MILESTONE_STEP = 500.0

# Pack keeping ---------------------------------------------------------------
# Cars far behind/ahead get speed nudges so the whole pack stays on camera.
RUBBER_BAND_DISTANCE = 45.0
RUBBER_BAND_BOOST = 1.35
RUBBER_BAND_SLOW = 0.90
# Hard cap on the pack's z-spread so cars never drive so far ahead that they
# shrink to a dot in the fixed camera. Leading cars hold at this distance from
# the trailing car.
PACK_MAX_SPREAD = 60.0

# Wide pack camera (used by the renderer) ------------------------------------
PACK_CAMERA_MIN_SPREAD = 70.0
PACK_CAMERA_MAX_SPREAD = 200.0
PACK_CAMERA_MIN_DISTANCE = 55.0
PACK_CAMERA_MAX_DISTANCE = 230.0
PACK_CAMERA_HEIGHT = 16.0
PACK_CAMERA_SMOOTHING = 3.5   # higher = snappier camera

# Rendering ------------------------------------------------------------------
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720
WINDOW_TITLE = "Gem Drive"
TARGET_FPS = 60
