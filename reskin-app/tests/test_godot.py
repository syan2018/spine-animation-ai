"""Native export checks, including optional real Godot/Spine pose comparison."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.backend.godot.exporter import export_spine, node_paths, write_character
from app.backend.godot.spine_import import UnsupportedSpine, evaluate, inspect_spine, load_character, read_atlas

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples/sombrero"
GODOT = os.environ.get("GODOT_BIN") or shutil.which("godot") or shutil.which("godot4")


@pytest.fixture
def simple(tmp_path):
    data = {
        "skeleton": {"spine": "4.2.0"},
        "bones": [{"name": "root", "x": 10, "y": 20, "rotation": 30, "scaleX": 1.3, "scaleY": 0.7},
                  {"name": "arm", "parent": "root", "x": 15, "y": 25, "rotation": 10, "scaleX": -1, "scaleY": 1.2}],
        "slots": [{"name": "hand", "bone": "arm", "attachment": "palm"}],
        "skins": [
            {"name": "default", "attachments": {"hand": {"palm": {"path": "part", "width": 8, "height": 12, "scaleX": -1}}}},
            {"name": "blue", "attachments": {"hand": {"palm": {"path": "other", "width": 8, "height": 12, "x": 4, "rotation": 15}}}},
        ],
        "animations": {
            "attack": {"bones": {"arm": {"rotate": [{"value": 20}, {"time": 1, "value": 60}]}}},
            "idle": {"bones": {"root": {"translate": [{"x": 0, "y": 0}, {"time": 1, "x": 2, "y": 3}]}}},
            "steps": {"bones": {"root": {"translatex": [{"value": 0, "curve": "stepped"}, {"time": 0.5, "value": 10}, {"time": 1, "value": 20}]}}},
            "delayed": {"bones": {"arm": {"rotate": [{"time": 0.5, "value": 90}, {"time": 1, "value": 0}]}}},
            "scale": {"bones": {"arm": {"scale": [{"x": 1, "y": 1}, {"time": 1, "x": 2, "y": 0.5}]}}},
        },
    }
    spine = tmp_path / "rig.json"
    spine.write_text(json.dumps(data), encoding="utf-8")
    sheet = Image.new("RGBA", (16, 12), "red")
    sheet.paste(Image.new("RGBA", (8, 12), "blue"), (8, 0))
    sheet.save(tmp_path / "sheet.png")
    spine.with_suffix(".atlas").write_text("sheet.png\nsize: 16,12\npart\nbounds: 0,0,8,12\nother\nbounds: 8,0,8,12\n")
    return spine


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_atlas_restores_trim_rotation_and_alpha(tmp_path, rotation):
    original = Image.new("RGBA", (3, 5), (0, 0, 0, 0))
    original.putpixel((0, 0), (255, 0, 0, 77))
    original.putpixel((2, 4), (0, 0, 255, 255))
    packed = original.rotate(rotation, expand=True)
    sheet = Image.new("RGBA", (20, 20))
    sheet.paste(packed, (2, 3))
    sheet.save(tmp_path / "page.png")
    atlas = tmp_path / "test.atlas"
    atlas.write_text(f"page.png\nsize: 20,20\npart\nbounds: 2,3,3,5\nrotate: {rotation}\noffsets: 1,2,7,10\n")
    restored = read_atlas(atlas)["part"]
    assert restored.size == (7, 10)
    assert restored.crop((1, 3, 4, 8)).tobytes() == original.tobytes()
    assert restored.getpixel((0, 0))[3] == 0


def test_curves_use_absolute_time_and_values():
    frames = [{"time": 2, "value": 10, "curve": [2.25, 10, 2.75, 30]}, {"time": 3, "value": 30}]
    assert evaluate(frames, 1, "value", 0, 0) == (0, True)
    assert evaluate(frames, 2.5, "value", 0, 0)[0] == pytest.approx(20)
    assert evaluate(frames, 3, "value", 0, 0) == (30, True)
    frames[0]["curve"] = "stepped"
    assert evaluate(frames, 2.99, "value", 0, 0) == (10, True)


@pytest.mark.parametrize("feature", ["ik", "deform", "mesh", "drawOrder", "events", "shear", "inherit"])
def test_unsupported_is_reported_before_writing(simple, tmp_path, feature):
    data = json.loads(simple.read_text())
    if feature == "ik":
        data["ik"] = [{"name": "leg"}]
    elif feature == "mesh":
        data["skins"][0]["attachments"]["hand"]["palm"]["type"] = "mesh"
    elif feature == "inherit":
        data["bones"][1]["inherit"] = "onlyTranslation"
    elif feature == "shear":
        data["bones"][1]["shearX"] = 15
    else:
        data["animations"]["idle"][feature] = [{"time": 1}]
    simple.write_text(json.dumps(data))
    output = tmp_path / "out"
    with pytest.raises(UnsupportedSpine) as error:
        export_spine(simple, output)
    assert feature.lower() in str(error.value).lower()
    assert not output.exists()


def test_skin_mapping_and_pose_reset(simple, tmp_path):
    model, textures = load_character(simple)
    assert textures[model["skins"]["default"]["hand"]["texture"]].getpixel((0, 0)) == (255, 0, 0, 255)
    assert textures[model["skins"]["blue"]["hand"]["texture"]].getpixel((0, 0)) == (0, 0, 255, 255)
    track = next(t for t in model["animations"]["idle"]["tracks"] if t["bone"] == "arm" and t["property"] == "rotation")
    assert track["values"] == [10]
    assert model["animations"]["idle"]["loop"] is True
    assert model["animations"]["attack"]["loop"] is False
    output = tmp_path / "export"
    write_character(model, textures, output)
    with pytest.raises(FileExistsError):
        write_character(model, textures, output)
    assert "Spine" not in (output / "character.gd").read_text()


def test_extra_skin_round_trip_and_wrong_rig(simple, tmp_path):
    from app.backend.godot.app_export import export_project
    from app.backend import projects
    data = json.loads(simple.read_text())
    data["skins"] = [data["skins"][0], {"name": "green", "attachments": data["skins"][1]["attachments"]}]
    extra = tmp_path / "rig-green.json"
    extra.write_text(json.dumps(data))
    extra.with_suffix(".atlas").write_bytes(simple.with_suffix(".atlas").read_bytes())
    model, _ = load_character(simple, extra_skins=[extra])
    assert set(model["skins"]) == {"default", "blue", "green"}
    # Generated looks are kept under .genie/skins in the app.
    (tmp_path / ".genie/skins/green").mkdir(parents=True)
    (tmp_path / ".genie/skins/green/layout_map.json").write_text("{}")
    project = projects.open_project(tmp_path)
    report = export_project(project, "green", {}, [])
    assert "green" in report["skins"]
    data["bones"][0]["x"] += 10
    extra.write_text(json.dumps(data))
    with pytest.raises(UnsupportedSpine, match="another rig"):
        load_character(simple, extra_skins=[extra])


def test_app_export_applies_edits_transforms_and_visibility(simple, monkeypatch):
    from fastapi.testclient import TestClient
    from app.backend import projects, server
    # projects.open_project normalizes compact atlases; use the standard form
    # here so this test stays in its own fixture directory.
    atlas = simple.with_suffix(".atlas")
    atlas.write_text(atlas.read_text().replace("bounds: 0,0,8,12", "xy: 0,0\nsize: 8,12").replace("bounds: 8,0,8,12", "xy: 8,0\nsize: 8,12"))
    project = projects.open_project(simple.parent)
    transforms = project.workdir / "transforms/default.json"
    transforms.parent.mkdir()
    transforms.write_text(json.dumps({"hand": {"x": 5, "y": 7, "rotation": 12, "scale": 2}}))
    monkeypatch.setattr(server._State, "project", project)
    client = TestClient(server.app)
    response = client.post("/api/export/godot", json={"skin_name": "default", "hidden": ["hand"], "edits": {"hand": {"brightness": -0.5}}})
    assert response.status_code == 200, response.text
    output = Path(response.json()["output_dir"])
    model = json.loads((output / "character.json").read_text())
    att = model["skins"]["default"]["hand"]
    assert (att["x"], att["y"], att["rotation"], att["scaleX"]) == (5, 7, 12, -2)
    assert model["hidden_parts"] == ["hand"]
    with Image.open(output / att["texture"]) as image:
        assert image.getpixel((0, 0))[0] in (127, 128)
    assert client.post("/api/export/godot", json={"skin_name": "missing"}).status_code == 400
    project.spine_json["ik"] = [{"name": "test"}]
    project.spine_json_path.write_text(json.dumps(project.spine_json))
    unsupported = client.post("/api/export/godot", json={})
    assert unsupported.status_code == 422
    assert "ik definitions" in unsupported.json()["detail"]["unsupported"]


@pytest.mark.parametrize("example", ["skeleton", "sombrero"])
def test_examples_export(example, tmp_path):
    report = export_spine(EXAMPLE / f"{example}.json", tmp_path / example)
    assert len(report["animations"]) == (6 if example == "skeleton" else 1)
    assert len(list((tmp_path / example / "textures").glob("*.png"))) == report["parts"]


@pytest.mark.skipif(not GODOT or not shutil.which("node"), reason="set GODOT_BIN and install frontend dependencies for engine checks")
@pytest.mark.parametrize("example", ["simple", "skeleton", "sombrero"])
def test_real_godot_matches_spine_and_switches_skins(example, simple, tmp_path):
    spine = simple if example == "simple" else EXAMPLE / f"{example}.json"
    model, textures = load_character(spine)
    output = tmp_path / "godot"
    write_character(model, textures, output)
    cases = [{"clip": name, "time": time} for name, clip in model["animations"].items()
             for time in (0, clip["duration"]*0.23, clip["duration"]*0.5, clip["duration"]-0.0001)]
    # Exercise attack -> idle on the same instance; absent tracks must reset.
    if "attack" in model["animations"]:
        cases += [{"clip": "attack", "time": 0.5}, {"clip": "idle", "time": 0}]
    (output / "probe_cases.json").write_text(json.dumps(cases))
    (output / "probe_paths.json").write_text(json.dumps(node_paths(model)[0]))
    shutil.copyfile(Path(__file__).with_name("godot_probe.gd"), output / "probe.gd")
    def run(args):
        completed = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert "SCRIPT ERROR" not in completed.stderr and "ERROR:" not in completed.stderr, completed.stderr
        return completed.stdout
    run([GODOT, "--headless", "--path", str(output), "--editor", "--import", "--quit"])
    assert "GODOT_PROBE_OK" in run([GODOT, "--headless", "--path", str(output), "--script", "res://probe.gd"])
    expected = json.loads(run(["node", str(Path(__file__).with_name("spine_reference.mjs")), str(spine), str(output / "probe_cases.json")]))
    actual = json.loads((output / "probe_result.json").read_text())
    for case, native, reference in zip(cases, actual, expected):
        for bone in native:
            # Spine's runtime approximates Beziers with a fixed subdivision;
            # this exporter solves them and samples at 60 Hz. Allow a small
            # visual tolerance, while still detecting sign/offset errors.
            assert native[bone][:4] == pytest.approx(reference[bone][:4], abs=0.015), (case, bone)
            assert native[bone][4:] == pytest.approx(reference[bone][4:], abs=0.6), (case, bone)
