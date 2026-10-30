from pathlib import Path

from drive_game import assets


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def test_sanitize_name():
    assert assets.sanitize_name("JayGeeAiForFun") == "jaygeeaiforfun"
    assert assets.sanitize_name("Jay Gee!") == "jay_gee"
    assert assets.sanitize_name("  ") == "viewer"


def test_safe_filename_blocks_paths_and_unsupported():
    assert assets.safe_filename("../../evil.glb") == "evil.glb"
    assert assets.safe_filename("My Car.OBJ") == "my_car.obj"
    assert assets.safe_filename("car.blend") is None
    assert assets.safe_filename("car.exe") is None


def test_resolve_model_path_relative_and_absolute(tmp_path):
    model = touch(tmp_path / "models" / "cars" / "default.glb")
    assert assets.resolve_model_path("models/cars/default.glb", tmp_path) == model
    assert assets.resolve_model_path(str(model), tmp_path) == model
    assert assets.resolve_model_path("models/cars/missing.glb", tmp_path) is None
    assert assets.resolve_model_path("models/cars/default.blend", tmp_path) is None


def test_fixed_camera_pose():
    position, look_at = assets.fixed_camera_pose(
        1.8, 100.0, (0.0, 32.0, -100.0), (0.0, 1.0, 30.0)
    )
    assert position == (1.8, 32.0, 0.0)
    assert look_at == (1.8, 1.0, 130.0)


def test_find_obj_texture(tmp_path):
    obj = tmp_path / "car.obj"
    obj.write_text(chr(10).join([
        "mtllib car.mtl",
        "v 0 0 0",
        "f 1 1 1",
    ]) + chr(10), encoding="utf-8")
    texture = touch(tmp_path / "palette.png")
    (tmp_path / "car.mtl").write_text(chr(10).join([
        "newmtl Body",
        "Kd 0.8 0.8 0.8",
        "map_Kd palette.png",
    ]) + chr(10), encoding="utf-8")
    assert assets.find_obj_texture(obj) == texture


def test_find_obj_texture_falls_back_to_basename(tmp_path):
    obj = tmp_path / "car.obj"
    obj.write_text("mtllib car.mtl" + chr(10), encoding="utf-8")
    texture = touch(tmp_path / "palette.png")
    (tmp_path / "car.mtl").write_text(
        "map_Kd C:" + chr(92) + "Users" + chr(92) + "someone" + chr(92) + "palette.png" + chr(10),
        encoding="utf-8",
    )
    assert assets.find_obj_texture(obj) == texture


def test_find_obj_texture_without_map(tmp_path):
    obj = tmp_path / "car.obj"
    obj.write_text("mtllib car.mtl" + chr(10), encoding="utf-8")
    (tmp_path / "car.mtl").write_text("Kd 0.8 0.8 0.8" + chr(10), encoding="utf-8")
    assert assets.find_obj_texture(obj) is None


def test_resolve_model_path_searches_common_folders(tmp_path):
    root_model = touch(tmp_path / "models" / "cars" / "root_car.obj")
    game_model = touch(tmp_path / "drive_game" / "models" / "cars" / "players" / "game_car.obj")
    assert assets.resolve_model_path("root_car.obj", tmp_path) == root_model
    assert assets.resolve_model_path("game_car.obj", tmp_path) == game_model
    assert assets.resolve_model_path("models/cars/root_car.obj", tmp_path) == root_model


def test_triangulate_obj_quads(tmp_path):
    obj = tmp_path / "car.obj"
    text = chr(10).join([
        "mtllib car.mtl",
        "v 0 0 0", "v 1 0 0", "v 1 0 1", "v 0 0 1", "v 2 0 0",
        "usemtl Body",
        "f 1 2 3 4",
        "f 1 3 5",
    ]) + chr(10)
    obj.write_text(text, encoding="utf-8")
    converted = assets.triangulate_obj_file(obj)
    assert converted.name == "car.tri.obj"
    result = converted.read_text(encoding="utf-8").splitlines()
    assert "usemtl Body" in result
    assert sum(line.startswith("f ") for line in result) == 3
    assert assets.triangulate_obj_file(obj) == converted


def test_triangulate_obj_skips_triangles(tmp_path):
    obj = tmp_path / "tri.obj"
    text = chr(10).join([
        "v 0 0 0", "v 1 0 0", "v 0 0 1", "f 1 2 3",
    ]) + chr(10)
    obj.write_text(text, encoding="utf-8")
    assert assets.triangulate_obj_file(obj) == obj
    assert not (tmp_path / "tri.tri.obj").exists()


def test_find_player_model_exact_and_sanitized(tmp_path):
    touch(tmp_path / "players" / "Jay Gee.obj")
    touch(tmp_path / "players" / "bob.glb")
    assert assets.find_player_model("Jay Gee", tmp_path / "players").name == "Jay Gee.obj"
    assert assets.find_player_model("jay gee", tmp_path / "players").name == "Jay Gee.obj"
    assert assets.find_player_model("bob", tmp_path / "players").name == "bob.glb"
    assert assets.find_player_model("alice", tmp_path / "players") is None


def test_find_player_model_extension_priority(tmp_path):
    touch(tmp_path / "bob.bam")
    touch(tmp_path / "bob.obj")
    touch(tmp_path / "bob.glb")
    assert assets.find_player_model("bob", tmp_path).suffix == ".glb"


def test_pick_model_for_user_falls_back(tmp_path):
    default = tmp_path / "default.glb"
    assert assets.pick_model_for_user("alice", tmp_path, default) == default
    player = touch(tmp_path / "alice.obj")
    assert assets.pick_model_for_user("alice", tmp_path, default) == player


def test_fit_scale():
    assert assets.fit_scale(2.0, 4.0, 4.2) == 1.05
    assert assets.fit_scale(4.0, 2.0, 4.2) == 1.05
    assert assets.fit_scale(0.0, 0.0, 4.2) == 1.0
    assert assets.fit_scale(2.0, 4.0, 4.2, manual_scale=2.5) == 2.5


def test_needs_yaw():
    assert assets.needs_yaw(5.0, 2.0)
    assert not assets.needs_yaw(2.0, 5.0)
    assert not assets.needs_yaw(4.0, 3.9)
