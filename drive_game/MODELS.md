# Custom car models

Gem Drive uses the built-in cube car when no model is configured. Drop your own
models into `models/cars/` (gitignored) and point the game at them.

## Quick start

1. Export your car from Blender as **glTF 2.0 (.glb)** (recommended) or **OBJ**.
   `.blend` files are not loaded directly — export them first.
2. Put the file in `models/cars/`:

   ```
   models/cars/
     default.glb          # fallback player car
     traffic.glb          # traffic car (optional)
     players/
       JayGeeAiForFun.glb # per-viewer car (chat name)
   ```

3. In the control panel → **Games → Car Models**, set the default car and/or
   traffic model paths, then click **Save model settings** (uploads save the
   path automatically).
   Or edit `config.py`:

   ```python
   GAME_DRIVE_CAR_MODEL = "models/cars/default.glb"
   GAME_DRIVE_TRAFFIC_MODEL = "models/cars/traffic.glb"
   GAME_DRIVE_PLAYER_MODEL_DIR = "models/cars/players"
   ```

4. Restart Gem Drive (`start_scripts/start_drive_game.bat`). Models are loaded
   at startup.

The panel can also upload files directly: **Upload car**, **Upload traffic**, or
**Upload player car** (enter the viewer's chat name first). Uploads to the
default/traffic slots save the config path for you.

Bare filenames are searched in both `models/cars/` and `drive_game/models/cars/`
(plus their `players/` subfolders), so dropping a model next to the game also
works. OBJ files with Blender-style quad faces are triangulated automatically.

## Demo mode (test settings without chat)

- **Control panel:** Games → Demo Mode → choose how many cars → **Apply demo mode**.
  The demo cars leave/join instantly on the running game.
- **Command line:** `python -m drive_game --demo --demo-cars 6`
  (add `--headless --ticks 900` for a simulation-only test).
- Demo cars are named `Demo 1`, `Demo 2`, … and auto-drive with lane changes,
  speed changes and brakes. They keep the road busy without any chat input.
- Demo cars always leave at least `GAME_DRIVE_DEMO_RESERVED_SLOTS` (default 2)
  grid slots free, and a real viewer's `!join` evicts a demo car if the grid
  fills up — so `!join` keeps working while demo mode is on.
- Demo crash/leader/milestone events are flagged and **not** sent to Gem's
  commentary, so testing won't make the stream talk.
- To test per-viewer models, name files `Demo 1.glb` or `demo_1.glb` (same
  matching rules as real viewers).
- **Reset race** keeps demo mode enabled; toggle **Enable** off and apply to stop.

## Per-viewer cars

The game looks for `models/cars/players/<chatname>.<ext>`.

- Exact chat name is tried first (case-insensitive), so
  `JayGeeAiForFun.glb` works.
- If not found, a sanitized version is tried: `Jay Gee` → `jay_gee.glb`.
- If neither exists, the default `GAME_DRIVE_CAR_MODEL` is used.
- If that is empty, the player gets the cube car.

Supported extensions: `.glb`, `.gltf`, `.obj`, `.bam`.
Preference when several exist for the same name: GLB > GLTF > OBJ > BAM.

## Scaling and orientation

Models are automatically scaled so their longest horizontal side matches the
car length (`tuning.CAR_LENGTH`, 4.2 units), centered on their footprint, and
placed with the bottom on the road.

- **Model yaw** (`GAME_DRIVE_MODEL_YAW`): extra rotation in degrees. `0` means
  auto-detect: a model longer along X is rotated 90°.
- **Model scale** (`GAME_DRIVE_MODEL_SCALE`): `0` = auto-fit. Set a number to
  override (e.g. `1.5`).
- **Y offset** (`GAME_DRIVE_MODEL_Y_OFFSET`): lift/lower the model if its
  wheels do not sit on the road.

Cars should face **+Z** after the yaw adjustment. If yours drives backwards,
set yaw to `180` (or adjust with `90`/`-90`).

Each player car gets a translucent-looking colored plate underneath in their
assigned color, so viewers can identify their car without recoloring the model.

## Traffic

`GAME_DRIVE_TRAFFIC_MODEL` replaces the red traffic cube. Traffic has no plate
or name label. If the path is empty or the file fails to load, the cube is used.

## Model requirements

- Low-poly: 12 player cars + up to 14 traffic cars are displayed at once.
  Aim for < ~50k triangles per car.
- GLB with embedded textures is the most reliable format. For OBJ, the game
  reads `map_Kd` from the MTL and applies the diffuse texture itself (Ursina's
  importer otherwise ignores it). Keep the `.mtl` and texture next to the OBJ;
  one diffuse texture per car is supported.
- If using `.gltf` with external `.bin`/textures, keep those files next to the
  model.
- Keep the model near the origin so auto-centering works well.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Still see cubes | Check the path in `config.py` / Games tab; use a supported extension; restart the game and read the `[GAME]` console warning |
| OBJ reports "triangles: 0" | Quads are auto-triangulated to a `.tri.obj` sibling; make sure the `.mtl` and textures are next to the OBJ |
| Car is white/untextured | For OBJ, check the MTL's `map_Kd` points to a texture next to the model; GLB embeds textures and is the safest option |
| Car points sideways/backwards | Set `GAME_DRIVE_MODEL_YAW` to `90`, `-90`, or `180` |
| Car floats/sinks | Adjust `GAME_DRIVE_MODEL_Y_OFFSET` |
| Model too big/small | Set `GAME_DRIVE_MODEL_SCALE` (0 = auto) |
| Wrong car for a viewer | File name must match the chat name or its sanitized form |
