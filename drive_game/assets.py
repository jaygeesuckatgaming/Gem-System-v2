"""Model-path helpers for Gem Drive.

Pure path/math helpers live here (no Ursina/Panda3D imports) so they can be
unit tested headlessly. `app.py` uses them to resolve and fit car models.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Optional

# Ursina's mesh importer supports these. `.blend` is intentionally excluded:
# Ursina only finds Blender installations in development mode, which this game
# does not use. Export .blend files to .glb or .obj instead.
SUPPORTED_EXTENSIONS = (".glb", ".gltf", ".obj", ".bam")

EXTENSION_PRIORITY = {extension: index for index, extension in enumerate(SUPPORTED_EXTENSIONS)}


def sanitize_name(name: str) -> str:
    """Turn a chat display name into a safe filename stem."""
    cleaned = re.sub(r"[^a-z0-9_-]+", "_", (name or "").strip().lower())
    cleaned = cleaned.strip("_")
    return cleaned or "viewer"


def safe_filename(filename: str) -> Optional[str]:
    """Return a sanitized upload filename, or None for unsupported files.

    Strips directories (prevents `../../evil.glb`) and only allows the
    extensions in SUPPORTED_EXTENSIONS.
    """
    base = Path(filename or "").name
    stem, extension = os.path.splitext(base)
    extension = extension.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        return None
    return f"{sanitize_name(stem)}{extension}"


def triangulate_obj_file(path: Path) -> Path:
    """Return an OBJ with polygon faces fan-triangulated.

    Ursina's OBJ importer fails on Blender-style quads (it reports 0
    triangles), so we write a `.tri.obj` sibling once and load that instead.
    Files that are already triangular are returned unchanged. The `.mtl`
    stays next to the generated file, so materials can still resolve.
    """
    path = Path(path)
    if path.suffix.lower() != ".obj":
        return path

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return path

    needs_conversion = any(
        line.startswith("f ") and len(line.split()) > 4 for line in lines
    )
    if not needs_conversion:
        return path

    output = path.with_name(f"{path.stem}.tri.obj")
    try:
        if output.exists() and output.stat().st_mtime >= path.stat().st_mtime:
            return output
    except OSError:
        pass

    converted = []
    for line in lines:
        if not line.startswith("f "):
            converted.append(line)
            continue
        vertices = line.split()[1:]
        if len(vertices) <= 3:
            converted.append("f " + " ".join(vertices))
            continue
        for index in range(1, len(vertices) - 1):
            converted.append(
                f"f {vertices[0]} {vertices[index]} {vertices[index + 1]}"
            )

    try:
        output.write_text("\n".join(converted) + "\n", encoding="utf-8")
    except OSError:
        return path
    return output


def fixed_camera_pose(
    mean_x: float,
    center_z: float,
    offset: tuple,
    look: tuple,
) -> tuple:
    """Return (position, look_at) for a fixed rig that follows the pack."""
    position = (
        mean_x + float(offset[0]),
        float(offset[1]),
        center_z + float(offset[2]),
    )
    look_at = (
        mean_x + float(look[0]),
        float(look[1]),
        center_z + float(look[2]),
    )
    return position, look_at


def find_obj_texture(obj_path: Path) -> Optional[Path]:
    """Find the diffuse texture referenced by an OBJ's MTL file.

    Ursina's OBJ importer only reads the MTL's `Kd` diffuse colour, so textured
    Blender exports render white unless we load `map_Kd` ourselves.
    """
    obj_path = Path(obj_path)
    if obj_path.suffix.lower() != ".obj":
        return None

    try:
        lines = obj_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    mtl_files = []
    for line in lines:
        if line.lower().startswith("mtllib "):
            for name in line.split()[1:]:
                candidate = obj_path.parent / name.strip('"')
                if candidate.is_file():
                    mtl_files.append(candidate)
    if not mtl_files:
        mtl_files = sorted(obj_path.parent.glob("*.mtl"))

    for mtl in mtl_files:
        try:
            mtl_lines = mtl.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in mtl_lines:
            if not line.lower().startswith("map_kd "):
                continue
            value = line.split(None, 1)[1].strip().strip('"').strip("'")
            if not value:
                continue
            candidates = []
            raw = Path(value)
            if raw.is_absolute():
                candidates.append(raw)
            candidates.append(mtl.parent / raw)
            candidates.append(obj_path.parent / raw.name)
            for candidate in candidates:
                try:
                    if candidate.is_file():
                        return candidate
                except OSError:
                    pass
    return None


def resolve_model_path(path: str, project_root: Path) -> Optional[Path]:
    """Resolve a config path against the project root (absolute paths allowed).

    Bare filenames are also looked up in the usual asset folders:
      models/cars/, models/cars/players/,
      drive_game/models/cars/, drive_game/models/cars/players/
    This makes a value like "Car.obj" work no matter which folder the user
    copied it into (Ursina's asset folder is drive_game/, which surprises
    people). Returns None when nothing matches or the format is unsupported.
    """
    if not path:
        return None
    raw = os.path.expandvars(os.path.expanduser(str(path).strip()))
    candidate = Path(raw)
    project_root = Path(project_root)

    candidates = []
    if candidate.is_absolute():
        candidates.append(candidate)
    else:
        for base in (project_root, project_root / "drive_game"):
            candidates.append(base / candidate)
        for base in (project_root, project_root / "drive_game"):
            cars = base / "models" / "cars"
            candidates.append(cars / candidate.name)
            candidates.append(cars / "players" / candidate.name)

    seen = set()
    for item in candidates:
        try:
            resolved = item.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if (
            resolved.is_file()
            and resolved.suffix.lower() in SUPPORTED_EXTENSIONS
        ):
            return resolved
    return None


def resolve_model_dir(path: str, project_root: Path) -> Path:
    """Resolve a model directory even if it does not exist yet."""
    raw = os.path.expandvars(os.path.expanduser(str(path or "").strip()))
    candidate = Path(raw) if raw else Path("models/cars/players")
    if not candidate.is_absolute():
        candidate = Path(project_root) / candidate
    return candidate


def find_player_model(
    user: str,
    directory: Path,
    extensions: Iterable[str] = SUPPORTED_EXTENSIONS,
) -> Optional[Path]:
    """Find a per-viewer model: exact chatname first, then sanitized name.

    Extension priority is GLB > GLTF > OBJ > BAM.
    """
    if not user or not directory:
        return None
    directory = Path(directory)
    if not directory.is_dir():
        return None

    allowed = {extension.lower() for extension in extensions}
    files = [
        item
        for item in directory.iterdir()
        if item.is_file() and item.suffix.lower() in allowed
    ]
    if not files:
        return None

    keys = [user.strip().lower(), sanitize_name(user)]
    for key in dict.fromkeys(keys):  # dedupe, preserve order
        matches = [item for item in files if item.stem.lower() == key]
        if matches:
            matches.sort(key=lambda item: EXTENSION_PRIORITY.get(item.suffix.lower(), 99))
            return matches[0]
    return None


def pick_model_for_user(
    user: str,
    player_directory: Path,
    default_model: Optional[Path],
) -> Optional[Path]:
    """Per-viewer model if present, otherwise the default model."""
    return find_player_model(user, player_directory) or default_model


def fit_scale(
    size_x: float,
    size_z: float,
    target_length: float,
    manual_scale: float = 0.0,
) -> float:
    """Scale a model so its longest horizontal axis matches target_length."""
    if manual_scale and manual_scale > 0:
        return float(manual_scale)
    length = max(abs(size_x), abs(size_z))
    if length < 1e-6:
        return 1.0
    return float(target_length) / length


def needs_yaw(size_x: float, size_z: float) -> bool:
    """True when a model is longer along X than Z (rotate it onto the road)."""
    return abs(size_x) > abs(size_z) * 1.15
