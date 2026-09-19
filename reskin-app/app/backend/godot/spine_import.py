"""Strict Spine 4.2 region import into a small, engine-neutral character model.

Coordinates stay Y-up in pixels and angles in degrees until scene emission.
Unsupported semantics are reported before any output is published.
"""
from __future__ import annotations

import bisect
import copy
import json
import math
from pathlib import Path

from PIL import Image


class UnsupportedSpine(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = sorted(set(issues))
        super().__init__("Unsupported Spine features: " + "; ".join(self.issues))


CHANNELS = {
    "rotate": [("rotation", "value", 0)],
    "translate": [("x", "x", 0), ("y", "y", 0)],
    "translatex": [("x", "value", 0)], "translatey": [("y", "value", 0)],
    "scale": [("scaleX", "x", 1), ("scaleY", "y", 1)],
    "scalex": [("scaleX", "value", 1)], "scaley": [("scaleY", "value", 1)],
}
DEFAULTS = {"x": 0, "y": 0, "rotation": 0, "scaleX": 1, "scaleY": 1}


def skins_of(data: dict) -> dict:
    skins = data.get("skins", [])
    if not isinstance(skins, list):
        raise UnsupportedSpine(["skins must use the Spine 4.2 array format"])
    return {s["name"]: s.get("attachments", {}) for s in skins}


def inspect_spine(data: dict) -> list[str]:
    issues = []
    version = data.get("skeleton", {}).get("spine", "")
    if version != "4.2" and not version.startswith("4.2."):
        issues.append(f"Spine version {version!r}; this importer targets 4.2")
    for key in ("ik", "transform", "path", "physics", "events"):
        if data.get(key):
            issues.append(f"{key} definitions")
    bones = data.get("bones", [])
    known = set()
    for bone in bones:
        name = bone["name"]
        if name in known or (bone.get("parent") and bone["parent"] not in known):
            issues.append(f"bone {name}: duplicate name or parent must precede child")
        known.add(name)
        if (bone.get("inherit", bone.get("transform", "normal")) != "normal"
                or bone.get("shearX", 0) or bone.get("shearY", 0) or bone.get("skin")):
            issues.append(f"bone {name}: shear, non-normal inheritance or skin-required bone")
    if not bones:
        issues.append("no bones")
    slots = set()
    for slot in data.get("slots", []):
        if slot["name"] in slots or slot["bone"] not in known:
            issues.append(f"slot {slot['name']}: duplicate name or unknown bone")
        slots.add(slot["name"])
        if slot.get("blend", "normal") != "normal" or slot.get("dark"):
            issues.append(f"slot {slot['name']}: blend mode or two-color tint")
    try:
        skins = skins_of(data)
    except UnsupportedSpine as exc:
        return issues + exc.issues
    if "default" not in skins:
        issues.append("missing default skin")
    for skin in data.get("skins", []):
        if any(skin.get(k) for k in ("bones", "ik", "transform", "path", "physics")):
            issues.append(f"skin {skin['name']}: skin-specific bones or constraints")
        for slot, atts in skin.get("attachments", {}).items():
            if slot not in slots or len(atts) > 1:
                issues.append(f"skin {skin['name']}/{slot}: unknown slot or multiple attachments")
            for name, att in atts.items():
                if att.get("type", "region") != "region" or att.get("sequence"):
                    issues.append(f"attachment {skin['name']}/{slot}/{name}: {att.get('type', 'region')} or sequence")
    for name, clip in data.get("animations", {}).items():
        if name == "RESET" or any(c in name for c in '/:[],'):
            issues.append(f"animation name {name!r} is reserved or invalid in Godot")
        for key, value in clip.items():
            if key != "bones" and value:
                issues.append(f"animation {name}: {key} timelines")
        for bone, timelines in clip.get("bones", {}).items():
            used = set()
            if bone not in known:
                issues.append(f"animation {name}: unknown bone {bone}")
            for kind, frames in timelines.items():
                if kind not in CHANNELS:
                    issues.append(f"animation {name}/{bone}: {kind} timeline")
                    continue
                channels = {c[0] for c in CHANNELS[kind]}
                if used & channels:
                    issues.append(f"animation {name}/{bone}: overlapping {kind} timelines")
                used.update(channels)
                previous = -1.0
                for index, frame in enumerate(frames):
                    t = frame.get("time", 0)
                    if not isinstance(t, (float, int)) or not math.isfinite(t) or t < 0 or t <= previous:
                        issues.append(f"animation {name}/{bone}/{kind}: invalid key times")
                    previous = t
                    if kind == "rotate" and "angle" in frame:
                        issues.append(f"animation {name}/{bone}: old angle keys; expected 4.2 value keys")
                    curve = frame.get("curve")
                    if curve not in (None, "stepped"):
                        if not isinstance(curve, list) or len(curve) != 4 * len(CHANNELS[kind]):
                            issues.append(f"animation {name}/{bone}/{kind}: invalid 4.2 Bezier curve")
                        elif index + 1 < len(frames):
                            end = frames[index + 1].get("time", 0)
                            for c in range(0, len(curve), 4):
                                if not (t - 1e-6 <= curve[c] <= end + 1e-6
                                        and t - 1e-6 <= curve[c + 2] <= end + 1e-6):
                                    issues.append(f"animation {name}/{bone}/{kind}: non-monotonic Bezier time")
    return sorted(set(issues))


def _safe_asset(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"asset path escapes its directory: {name}")
    return path


def read_atlas(path: Path) -> dict[str, Image.Image]:
    """Restore trimmed/rotated regions, including modern bounds/offsets.

    Spine's size/bounds dimensions describe the unrotated region; a 90-degree
    packed region occupies height x width pixels on the page.
    """
    blocks = []
    block = []
    for raw in path.read_text(encoding="utf-8").splitlines() + [""]:
        if not raw.strip():
            if block:
                blocks.append(block)
                block = []
        else:
            block.append(raw.strip())
    result = {}
    for block in blocks:
        page_path = _safe_asset(path.parent, block[0])
        with Image.open(page_path) as opened:
            sheet = opened.convert("RGBA")
        cursor = 1
        page_props = {}
        while cursor < len(block) and ":" in block[cursor]:
            k, v = block[cursor].split(":", 1)
            page_props[k] = v.strip()
            cursor += 1
        if page_props.get("pma", "false") == "true":
            import numpy as np
            rgba = np.array(sheet, dtype=np.float32)
            alpha = rgba[..., 3:4]
            rgba[..., :3] = np.where(alpha > 0, np.minimum(255, rgba[..., :3] * 255 / np.maximum(alpha, 1)), 0)
            sheet = Image.fromarray(np.rint(rgba).astype("uint8"))
        while cursor < len(block):
            name = block[cursor]
            cursor += 1
            props = {}
            while cursor < len(block) and ":" in block[cursor]:
                k, v = block[cursor].split(":", 1)
                props[k] = v.strip()
                cursor += 1
            def ints(key, default):
                return tuple(int(v.strip()) for v in props[key].split(",")) if key in props else default
            if name in result or int(props.get("index", -1)) != -1:
                raise UnsupportedSpine([f"atlas indexed/duplicate region {name}"])
            if "bounds" in props:
                x, y, w, h = ints("bounds", ())
            else:
                x, y = ints("xy", (0, 0))
                w, h = ints("size", (0, 0))
            rot = props.get("rotate", "false").lower()
            degrees = 90 if rot == "true" else 0 if rot == "false" else int(rot)
            if degrees not in (0, 90, 180, 270):
                raise UnsupportedSpine([f"atlas rotation {degrees}"])
            pw, ph = (h, w) if degrees in (90, 270) else (w, h)
            if min(w, h) <= 0 or min(x, y) < 0 or x + pw > sheet.width or y + ph > sheet.height:
                raise ValueError(f"atlas region outside page: {name}")
            part = sheet.crop((x, y, x + pw, y + ph)).rotate(-degrees, expand=True)
            if "offsets" in props:
                ox, oy, ow, oh = ints("offsets", ())
            else:
                ox, oy = ints("offset", (0, 0))
                ow, oh = ints("orig", (w, h))
            if min(ox, oy) < 0 or ox + w > ow or oy + h > oh:
                raise ValueError(f"invalid trim offsets: {name}")
            restored = Image.new("RGBA", (ow, oh))
            restored.paste(part, (ox, oh - oy - h))
            result[name] = restored
    return result


def evaluate(frames: list[dict], time: float, key: str, default: float, channel: int) -> tuple[float, bool]:
    """Evaluate one 4.2 timeline component and whether its next span is held."""
    index = bisect.bisect_right([f.get("time", 0) for f in frames], time) - 1
    if index < 0:
        return default, True
    first = frames[index]
    a = first.get(key, default)
    if index == len(frames) - 1 or first.get("curve") == "stepped":
        return a, True
    last = frames[index + 1]
    t0, t1 = first.get("time", 0), last.get("time", 0)
    b = last.get(key, default)
    curve = first.get("curve")
    if not curve:
        return a + (b - a) * (time - t0) / (t1 - t0), False
    cx1, cy1, cx2, cy2 = curve[channel * 4:channel * 4 + 4]
    def bezier(p0, p1, p2, p3, u):
        return (1-u)**3*p0 + 3*(1-u)**2*u*p1 + 3*(1-u)*u*u*p2 + u**3*p3
    low, high = 0.0, 1.0
    for _ in range(35):
        mid = (low + high) / 2
        if bezier(t0, cx1, cx2, t1, mid) < time:
            low = mid
        else:
            high = mid
    return bezier(a, cy1, cy2, b, (low + high) / 2), False


def bake_animations(data: dict, fps: int, loops: set[str]) -> dict:
    clips = {}
    for name, animation in data.get("animations", {}).items():
        source = animation.get("bones", {})
        duration = max((f.get("time", 0) for b in source.values() for fs in b.values() for f in fs), default=0)
        duration = max(duration, 1 / fps)
        if duration > 600:
            raise ValueError("animation exceeds the 10-minute export limit")
        tracks = []
        for bone in data["bones"]:
            by_property = {}
            for kind, frames in source.get(bone["name"], {}).items():
                for index, (prop, key, default) in enumerate(CHANNELS[kind]):
                    by_property[prop] = (frames, key, default, index)
            # Explicit setup values in every clip avoid previous-action pose
            # leaking into a clip which never authored that bone/property.
            for prop, setup_default in DEFAULTS.items():
                setup = bone.get(prop, setup_default)
                timeline = by_property.get(prop)
                if not timeline or not timeline[0]:
                    times, values, holds = [0.0], [setup], [True]
                else:
                    frames, key, default, index = timeline
                    times = sorted({0.0, float(duration), *(f.get("time", 0) for f in frames),
                                    *(i / fps for i in range(math.ceil(duration * fps)))})
                    values, holds = [], []
                    for time in times:
                        value, held = evaluate(frames, time, key, default, index)
                        values.append(setup * value if prop.startswith("scale") else setup + value)
                        holds.append(held)
                tracks.append({"bone": bone["name"], "property": prop, "times": times, "values": values, "holds": holds})
        clips[name] = {"duration": duration, "loop": name in loops, "tracks": tracks}
    return clips


def load_character(spine_path: Path, atlas_path: Path | None = None, *,
                   extra_skins: list[Path] | None = None, fps: int = 60,
                   loops: set[str] | None = None) -> tuple[dict, dict[str, Image.Image]]:
    if not 12 <= fps <= 120:
        raise ValueError("sample rate must be between 12 and 120")
    data = json.loads(spine_path.read_text(encoding="utf-8"))
    issues = inspect_spine(data)
    if issues:
        raise UnsupportedSpine(issues)
    source_skins = skins_of(data)
    atlas_path = atlas_path or spine_path.with_suffix(".atlas")
    atlas = read_atlas(atlas_path)
    sources = {name: atlas for name in source_skins}
    for extra_path in extra_skins or []:
        extra = json.loads(extra_path.read_text(encoding="utf-8"))
        issues = inspect_spine(extra)
        if any(extra.get(k) != data.get(k) for k in ("bones", "slots", "animations")):
            issues.append(f"skin file {extra_path.name} belongs to another rig or animation set")
        if issues:
            raise UnsupportedSpine(issues)
        extra_atlas = read_atlas(extra_path.with_suffix(".atlas"))
        for name, attachments in skins_of(extra).items():
            if name in source_skins:
                if attachments != source_skins[name]:
                    raise ValueError(f"conflicting skin {name} in {extra_path.name}")
                continue
            source_skins[name], sources[name] = attachments, extra_atlas
    model = {
        "schema_version": 1, "coordinates": "y_up_pixels_degrees",
        "name": spine_path.stem,
        "bones": [{"name": b["name"], "parent": b.get("parent"), "length": b.get("length", 0),
                   **{p: b.get(p, d) for p, d in DEFAULTS.items()}} for b in data["bones"]],
        "slots": copy.deepcopy(data.get("slots", [])), "skins": {},
        "animations": bake_animations(data, fps, {"idle", "walk", "run"} if loops is None else loops),
        "sample_fps": fps,
    }
    textures = {}
    for skin_index, (skin_name, attachments) in enumerate(source_skins.items()):
        normalized = {}
        for slot_index, slot in enumerate(model["slots"]):
            slot_name, key = slot["name"], slot.get("attachment")
            available = attachments.get(slot_name, {})
            fallback = source_skins["default"].get(slot_name, {})
            if key is not None and key not in available and key not in fallback:
                raise ValueError(f"missing setup attachment {skin_name}/{slot_name}/{key}")
            att = available.get(key, fallback.get(key))
            if att is None:
                normalized[slot_name] = None
                continue
            region = att.get("path", att.get("name", key))
            texture_atlas = sources[skin_name] if key in available else sources["default"]
            if region not in texture_atlas:
                raise ValueError(f"missing atlas region {region!r} for {skin_name}/{slot_name}")
            texture = texture_atlas[region]
            texture_key = f"textures/skin_{skin_index}_part_{slot_index}.png"
            textures[texture_key] = texture.copy()
            normalized[slot_name] = {
                **{p: att.get(p, d) for p, d in DEFAULTS.items()},
                "texture": texture_key, "width": att.get("width", texture.width),
                "height": att.get("height", texture.height), "color": att.get("color", "ffffffff"),
            }
        model["skins"][skin_name] = normalized
    # Catch NaN/Infinity in JSON before they turn into invalid Godot properties.
    json.dumps(model, allow_nan=False)
    return model, textures
