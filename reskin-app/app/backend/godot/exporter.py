"""Emit relocatable Godot 4 text resources; exporting does not need Godot installed."""
from __future__ import annotations

import json
import math
import re
import shutil
import uuid
from pathlib import Path

from .spine_import import DEFAULTS, load_character


def _q(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _n(value) -> str:
    if not math.isfinite(float(value)):
        raise ValueError("nonfinite transform")
    text = format(float(value), ".10g")
    # Variant animation values must stay floats even at 0/1. An integer first
    # key makes Godot interpolate integer values, rounding small rotations.
    return text if "." in text or "e" in text else text + ".0"


def _vec(x, y):
    return f"Vector2({_n(x)}, {_n(y)})"


def _color(value: str) -> list[float]:
    if len(value) == 6:
        value += "ff"
    if len(value) != 8:
        raise ValueError(f"invalid RGBA color {value!r}")
    return [int(value[i:i+2], 16) / 255 for i in range(0, 8, 2)]


def node_paths(model: dict) -> tuple[dict, dict]:
    bones = {}
    for index, bone in enumerate(model["bones"]):
        readable = re.sub(r"[^a-zA-Z0-9_-]", "_", bone["name"])[:48]
        name = f"b{index:03}_{readable}"
        parent = bones[bone["parent"]] if bone["parent"] else "Skeleton2D"
        bones[bone["name"]] = parent + "/" + name
    parts = {s["name"]: bones[s["bone"]] + f"/part_{i:03}" for i, s in enumerate(model["slots"])}
    return bones, parts


def _native_value(prop, value):
    return -math.radians(value) if prop == "rotation" else -value if prop == "y" else value


def _animation_resource(model, bones):
    properties = {"x": "position:x", "y": "position:y", "rotation": "rotation",
                  "scaleX": "scale:x", "scaleY": "scale:y"}
    reset = {"duration": 0.001, "loop": False, "tracks": [
        {"bone": b["name"], "property": p, "times": [0], "values": [b[p]], "holds": [True]}
        for b in model["bones"] for p in DEFAULTS
    ]}
    clips = {"RESET": reset, **model["animations"]}
    lines = [f'[gd_resource type="AnimationLibrary" load_steps={len(clips)+1} format=3]', ""]
    entries = []
    for i, (name, clip) in enumerate(clips.items()):
        rid = f"Animation_{i}"
        entries.append(f'{_q(name)}: SubResource({_q(rid)})')
        lines += [f'[sub_resource type="Animation" id={_q(rid)}]',
                  f'resource_name = {_q(name)}', f'length = {_n(clip["duration"])}',
                  f'loop_mode = {1 if clip["loop"] else 0}', f'step = {_n(1/model["sample_fps"])}']
        for j, track in enumerate(clip["tracks"]):
            prop = track["property"]
            path = bones[track["bone"]] + ":" + properties[prop]
            times = ", ".join(_n(t) for t in track["times"])
            transitions = ", ".join("0" if held else "1" for held in track["holds"])
            values = ", ".join(_n(_native_value(prop, v)) for v in track["values"])
            lines += [f'tracks/{j}/type = "value"', f'tracks/{j}/path = NodePath({_q(path)})',
                      f'tracks/{j}/interp = 1', f'tracks/{j}/loop_wrap = false',
                      f'tracks/{j}/keys = {{"times": PackedFloat32Array({times}), '
                      f'"transitions": PackedFloat32Array({transitions}), "update": 0, "values": [{values}]}}']
        lines.append("")
    lines += ["[resource]", "_data = {" + ",\n".join(entries) + "}", ""]
    return "\n".join(lines)


def _attachment(att, slot, textures, ids):
    if att is None:
        return "{}", []
    image = textures[att["texture"]]
    x, y, rotation = att["x"], -att["y"], -math.radians(att["rotation"])
    scale = _vec(att["scaleX"] * att["width"] / image.width, att["scaleY"] * att["height"] / image.height)
    rgba = [a*b for a, b in zip(_color(att["color"]), _color(slot.get("color", "ffffffff")))]
    color = "Color(" + ", ".join(_n(v) for v in rgba) + ")"
    values = {"texture": f'ExtResource({_q(ids[att["texture"]])})', "position": _vec(x, y),
              "rotation": _n(rotation), "scale": scale, "color": color}
    raw = "{" + ", ".join(f"{_q(k)}: {v}" for k, v in values.items()) + "}"
    properties = [f'{"self_modulate" if k == "color" else k} = {v}' for k, v in values.items()]
    return raw, properties


def _scene(model, textures, initial_skin):
    bones, parts = node_paths(model)
    ids = {path: f"Texture_{i}" for i, path in enumerate(textures)}
    lines = [f'[gd_scene load_steps={len(ids)+3} format=3]', "",
             '[ext_resource type="Script" path="character.gd" id="Character"]',
             '[ext_resource type="AnimationLibrary" path="animations.tres" id="Animations"]']
    for path, rid in ids.items():
        lines.append(f'[ext_resource type="Texture2D" path={_q(path)} id={_q(rid)}]')
    skin_values = {}
    defaults = {}
    for name, skin in model["skins"].items():
        attachments = []
        for slot in model["slots"]:
            raw, properties = _attachment(skin[slot["name"]], slot, textures, ids)
            attachments.append(f'{_q(slot["name"])}: {raw}')
            if name == initial_skin:
                defaults[slot["name"]] = properties
        skin_values[name] = "{" + ",\n".join(attachments) + "}"
    lines += ["", '[node name="Character" type="Node2D"]', 'script = ExtResource("Character")',
              "texture_filter = 2", f'current_skin = {_q(initial_skin)}',
              'hidden_parts = Array[String](' + _q(model.get("hidden_parts", [])) + ')',
              'parts = {' + ", ".join(f'{_q(k)}: {_q(v)}' for k, v in parts.items()) + '}',
              'skins = {' + ",\n".join(f'{_q(k)}: {v}' for k, v in skin_values.items()) + '}',
              "", '[node name="Skeleton2D" type="Skeleton2D" parent="."]']
    for bone in model["bones"]:
        parent, name = bones[bone["name"]].rsplit("/", 1)
        angle = -math.radians(bone["rotation"])
        sx, sy = bone["scaleX"], bone["scaleY"]
        c, s = math.cos(angle), math.sin(angle)
        rest = ", ".join(_n(v) for v in (c*sx, s*sx, -s*sy, c*sy, bone["x"], -bone["y"]))
        lines += ["", f'[node name={_q(name)} type="Bone2D" parent={_q(parent)}]',
                  f'position = {_vec(bone["x"], -bone["y"])}', f'rotation = {_n(angle)}',
                  f'scale = {_vec(sx, sy)}', f'rest = Transform2D({rest})',
                  'auto_calculate_length_and_angle = false', f'length = {_n(max(1, bone["length"]))}']
    for i, slot in enumerate(model["slots"]):
        parent, name = parts[slot["name"]].rsplit("/", 1)
        lines += ["", f'[node name={_q(name)} type="Sprite2D" parent={_q(parent)}]',
                  f'z_index = {i}', 'z_as_relative = false']
        lines += defaults[slot["name"]] or ["visible = false"]
        if defaults[slot["name"]] and slot["name"] in model.get("hidden_parts", []):
            lines.append("visible = false")
    lines += ["", '[node name="AnimationPlayer" type="AnimationPlayer" parent="."]',
              'libraries = {&"": ExtResource("Animations")}', ""]
    return "\n".join(lines)


def _preview_transform(model, textures, initial_skin):
    # Bound transformed corners in setup pose; do not trust skeleton metadata
    # bounds, which often omit hats, hands or updated skins.
    world = {}
    for b in model["bones"]:
        a = -math.radians(b["rotation"])
        c, s = math.cos(a), math.sin(a)
        local = (c*b["scaleX"], s*b["scaleX"], -s*b["scaleY"], c*b["scaleY"], b["x"], -b["y"])
        world[b["name"]] = _multiply(world[b["parent"]], local) if b["parent"] else local
    points = []
    for slot in model["slots"]:
        att = model["skins"][initial_skin][slot["name"]]
        if att is None:
            continue
        a = -math.radians(att["rotation"])
        c, s = math.cos(a), math.sin(a)
        matrix = _multiply(world[slot["bone"]], (c*att["scaleX"], s*att["scaleX"], -s*att["scaleY"], c*att["scaleY"], att["x"], -att["y"]))
        for x in (-att["width"]/2, att["width"]/2):
            for y in (-att["height"]/2, att["height"]/2):
                points.append((matrix[0]*x + matrix[2]*y + matrix[4], matrix[1]*x + matrix[3]*y + matrix[5]))
    if not points:
        return (480, 370, 1)
    left, right = min(p[0] for p in points), max(p[0] for p in points)
    top, bottom = min(p[1] for p in points), max(p[1] for p in points)
    scale = min(760/max(right-left, 1), 510/max(bottom-top, 1), 2)
    return 480 - (left+right)/2*scale, 370 - (top+bottom)/2*scale, scale


def _multiply(a, b):
    return (a[0]*b[0]+a[2]*b[1], a[1]*b[0]+a[3]*b[1],
            a[0]*b[2]+a[2]*b[3], a[1]*b[2]+a[3]*b[3],
            a[0]*b[4]+a[2]*b[5]+a[4], a[1]*b[4]+a[3]*b[5]+a[5])


def write_character(model, textures, output: Path, *, initial_skin="default") -> dict:
    """Publish a complete new directory; never overwrite a user's Godot scene."""
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"output already exists; choose a new directory: {output}")
    if initial_skin not in model["skins"]:
        raise ValueError(f"unknown initial skin {initial_skin}")
    bones, parts = node_paths(model)
    scene = _scene(model, textures, initial_skin)
    animations = _animation_resource(model, bones)
    x, y, scale = _preview_transform(model, textures, initial_skin)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f".{output.name}-{uuid.uuid4().hex}.staging"
    staging.mkdir()
    for path, texture in textures.items():
        target = staging / path
        target.parent.mkdir(parents=True, exist_ok=True)
        texture.save(target)
    for name in ("character.gd", "demo.gd"):
        shutil.copyfile(Path(__file__).with_name(name), staging / name)
    (staging / "character.tscn").write_text(scene, encoding="utf-8")
    (staging / "animations.tres").write_text(animations, encoding="utf-8")
    (staging / "character.json").write_text(json.dumps(model, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    (staging / "project.godot").write_text('''config_version=5
[application]
config/name="Native Cutout Preview"
run/main_scene="res://demo.tscn"
config/features=PackedStringArray("4.3", "GL Compatibility")
[display]
window/size/viewport_width=960
window/size/viewport_height=720
[rendering]
renderer/rendering_method="gl_compatibility"
environment/defaults/default_clear_color=Color(0.12, 0.14, 0.18, 1)
''', encoding="utf-8")
    (staging / "demo.tscn").write_text(f'''[gd_scene load_steps=3 format=3]
[ext_resource type="PackedScene" path="character.tscn" id="Character"]
[ext_resource type="Script" path="demo.gd" id="Demo"]
[node name="Preview" type="Node2D"]
script = ExtResource("Demo")
[node name="Character" parent="." instance=ExtResource("Character")]
position = {_vec(x, y)}
scale = {_vec(scale, scale)}
''', encoding="utf-8")
    report = {"status": "exported", "schema_version": 1, "target": "Godot 4 native cutout",
              "output_dir": str(output), "scene": str(output / "character.tscn"),
              "project": str(output / "project.godot"), "bones": len(bones), "parts": len(parts),
              "skins": list(model["skins"]), "animations": list(model["animations"]),
              "sample_fps": model["sample_fps"], "unsupported": [],
              "notes": ["Bezier tracks are sampled; linear interpolation between samples.",
                        "Default loops: idle/walk/run. Other clips play once unless overridden.",
                        "No Spine runtime is used by the exported scene."]}
    (staging / "import_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    staging.rename(output)
    return report


def export_spine(spine_path: Path, output: Path, **kwargs) -> dict:
    initial_skin = kwargs.pop("initial_skin", "default")
    model, textures = load_character(spine_path, **kwargs)
    return write_character(model, textures, output, initial_skin=initial_skin)
