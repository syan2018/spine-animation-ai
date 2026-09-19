"""Adapt the open editor project and pending edits to the native exporter."""
import json
import uuid
from dataclasses import fields

from ..imaging import SlotEdit, apply_edit
from .exporter import write_character
from .spine_import import load_character, skins_of


def export_project(project, skin_name: str, edits: dict, hidden: list[str], fps=60):
    if json.loads(project.spine_json_path.read_text(encoding="utf-8")) != project.spine_json:
        raise ValueError("the skeleton changed on disk; reopen the project before exporting")
    if skin_name not in project.to_payload()["skins"]:
        raise ValueError(f"unknown look {skin_name!r}")
    extra = []
    if skin_name not in skins_of(project.spine_json):
        skin_json = (project.path / f"{project.spine_json_path.stem}-{skin_name}.json").resolve()
        if not skin_json.is_relative_to(project.path.resolve()):
            raise ValueError("skin path escapes project")
        if not skin_json.is_file():
            raise ValueError("this look has no packed JSON/atlas yet; finish generating or rebaking it first")
        extra.append(skin_json)
    model, textures = load_character(project.spine_json_path, extra_skins=extra, fps=fps)
    slot_names = {s["name"] for s in model["slots"]}
    if not set(edits).issubset(slot_names) or not set(hidden).issubset(slot_names):
        raise ValueError("edits contain unknown parts; refresh the project")
    edit_fields = {f.name for f in fields(SlotEdit)}
    for name, attachments in model["skins"].items():
        transform_path = (project.workdir / "transforms" / f"{name}.json").resolve()
        if not transform_path.is_relative_to(project.workdir.resolve()):
            raise ValueError("transform path escapes project")
        transforms = json.loads(transform_path.read_text(encoding="utf-8")) if transform_path.exists() else {}
        for slot, att in attachments.items():
            if att is None:
                continue
            transform = transforms.get(slot, {})
            for prop in ("x", "y", "rotation"):
                att[prop] += transform.get(prop, 0)
            for prop in ("scaleX", "scaleY"):
                att[prop] *= transform.get("scale", 1)
            if name == skin_name and edits.get(slot):
                edit = SlotEdit(**{k: v for k, v in edits[slot].items() if k in edit_fields})
                textures[att["texture"]] = apply_edit(textures[att["texture"]], edit)
    model["hidden_parts"] = hidden
    output = project.workdir / "exports/godot" / uuid.uuid4().hex
    return write_character(model, textures, output, initial_skin=skin_name)
