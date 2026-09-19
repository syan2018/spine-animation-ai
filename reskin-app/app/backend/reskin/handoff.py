"""Persistent prepare/import jobs for images generated outside the app.

No image-generation or segmentation API is called here. Prepared assets are
immutable, and an import always creates a new skin using original alpha masks.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .. import settings
from ..ai.sam_provider import SAMProvider
from ..spine import atlas_reader
from .atlas_rebake import rebake_skin
from .pipeline import finish_reskin, prepare_reskin

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
_LOCK = threading.RLock()


class HandoffConflict(ValueError):
    """A job no longer matches its project or would replace an existing skin."""


def validate_skin_name(name: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", name):
        raise ValueError("look name must be 1–48 lowercase letters, digits, hyphens or underscores")
    if name in {"default", "con", "prn", "aux", "nul"} or re.fullmatch(r"(?:com|lpt)[0-9]", name):
        raise ValueError("choose a different look name; this name is reserved")
    return name


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("path escapes the project")
    return path


def _job_dir(project, job_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ValueError("invalid handoff ID")
    return _inside(project.path, f".genie/handoffs/{job_id}")


def _write_manifest(job_dir: Path, manifest: dict) -> None:
    temp = job_dir / "manifest.tmp"
    temp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(job_dir / "manifest.json")


def get_handoff(project, job_id: str) -> dict:
    with _LOCK:
        path = _job_dir(project, job_id) / "manifest.json"
        if not path.is_file():
            raise FileNotFoundError("handoff not found in the open project")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if (manifest["project_path"] != str(project.path.resolve())
                or manifest["spine_json"] != project.spine_json_path.name):
            raise HandoffConflict("handoff belongs to a different character")
        return manifest


def list_handoffs(project) -> list[dict]:
    directory = _inside(project.path, ".genie/handoffs")
    jobs = []
    for path in sorted(directory.glob("*/manifest.json")):
        try:
            jobs.append(get_handoff(project, path.parent.name))
        except (ValueError, KeyError, OSError):
            continue
    return sorted(jobs, key=lambda job: job["created_at"], reverse=True)


def _ensure_new_skin(project, name: str) -> None:
    validate_skin_name(name)
    base = f"{project.spine_json_path.stem}-{name}"
    if (name in project.skins or (project.workdir / "skins" / name).exists()
            or any((project.path / f"{base}{suffix}").exists() for suffix in (".json", ".png", ".atlas"))):
        raise HandoffConflict("that look already exists; prepare a task with a new look name")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_handoff(project, skin_name: str, prompt: str, method: str = "exploded") -> dict:
    with _LOCK:
        _ensure_new_skin(project, skin_name)
        if not prompt.strip():
            raise ValueError("a prompt is required")
        pair = atlas_reader.find_atlas_pair(project.path, project.spine_json_path.stem)
        if method == "atlas" and pair is None:
            raise ValueError("atlas mode requires an atlas and its image")
        source_paths = {project.spine_json_path}
        if pair:
            source_paths.update(pair)
        source_paths.update(
            p for p in project.path.glob("*.png")
            if not p.with_suffix(".atlas").exists() and not p.stem.startswith("Spine-")
        )
        source_hashes = {p.relative_to(project.path).as_posix(): _digest(p) for p in source_paths}
        # The in-memory skeleton is used during rebake. Do not prepare from a
        # stale open project if the user edited its JSON on disk.
        if json.loads(project.spine_json_path.read_text(encoding="utf-8")) != project.spine_json:
            raise HandoffConflict("the skeleton changed; reopen the project before preparing")
        job_id = uuid.uuid4().hex
        job_dir = _job_dir(project, job_id)
        job_dir.mkdir(parents=True)
        config = settings.load_settings()
        reference = None
        if config.reference.enabled and settings.has_reference_image():
            reference = job_dir / "style-reference.png"
            shutil.copy2(settings.reference_image_path(), reference)
        prepared = prepare_reskin(
            project.path, job_dir, skin_name, prompt, method=method,
            atlas_path=pair[0] if pair else None,
            atlas_sheet_path=pair[1] if pair else None,
            reference_image_path=reference,
            reference_prompt=config.reference.prompt,
        )
        with Image.open(prepared["composite_path"]) as image:
            source = image.convert("RGBA")
        # Fixed, familiar image-tool canvas ratios, with an explicit inverse
        # transform. Never stretch a generated image to an unrelated ratio.
        sizes = [(1024, 1024), (1536, 1024), (1024, 1536)]
        width, height = min(sizes, key=lambda size: abs(math.log((size[0] / size[1]) / (source.width / source.height))))
        scale = min(width / source.width, height / source.height)
        w, h = max(1, round(source.width * scale)), max(1, round(source.height * scale))
        x, y = (width - w) // 2, (height - h) // 2
        canvas = Image.new("RGBA", (width, height), "white")
        scaled = source.resize((w, h), Image.Resampling.LANCZOS)
        canvas.paste(scaled, (x, y), scaled)
        input_path = job_dir / "input.png"
        canvas.save(input_path)
        generation_prompt = (
            prepared["prompt"] + "\n\nConstraints: " + prepared["negative_prompt"]
            + f"\nThe LAST input image is the edit target on a {width} x {height} canvas. "
            + "Keep the canvas aspect ratio and all surrounding white padding. "
            + "Return only the complete edited target image, without cropping, labels or borders. "
            + "Keep each part's silhouette unchanged; the import will reuse its original alpha mask."
        )
        (job_dir / "prompt.txt").write_text(generation_prompt, encoding="utf-8")
        manifest = {
            "version": 1, "id": job_id, "status": "prepared",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "project_path": str(project.path.resolve()),
            "spine_json": project.spine_json_path.name,
            "skin_name": skin_name, "method": method, "user_prompt": prompt,
            "prompt": generation_prompt, "manifest_path": str(job_dir / "manifest.json"),
            "input_images": [str(p) for p in prepared["reference_images"]] + [str(input_path)],
            "input_image": input_path.relative_to(project.path).as_posix(),
            "expected_size": [width, height], "content_rect": [x, y, w, h],
            "layout": prepared["layout"], "source_hashes": source_hashes,
            "result": None, "rebake": None,
        }
        # Include prepared inputs in the validation; edits must use exactly
        # the layout that was handed to the image tool.
        for p in [input_path, prepared["composite_path"], job_dir / skin_name / "layout_map.json"]:
            manifest["source_hashes"][p.relative_to(project.path).as_posix()] = _digest(p)
        _write_manifest(job_dir, manifest)
        return manifest


def import_handoff(project, job_id: str, body: bytes) -> dict:
    with _LOCK:
        manifest = get_handoff(project, job_id)
        digest = hashlib.sha256(body).hexdigest()
        if manifest["status"] == "imported":
            if manifest.get("result_sha256") == digest:
                return manifest
            raise HandoffConflict("this task already has a result; prepare a new task for another version")
        if not body or len(body) > MAX_UPLOAD_BYTES:
            raise ValueError("upload a nonempty PNG, JPEG or WebP of at most 25 MiB")
        for relative, expected in manifest["source_hashes"].items():
            path = _inside(project.path, relative)
            if not path.is_file() or _digest(path) != expected:
                raise HandoffConflict("source assets changed; prepare a new task before importing")
        if json.loads(project.spine_json_path.read_text(encoding="utf-8")) != project.spine_json:
            raise HandoffConflict("the open skeleton is stale; reopen the project")
        name = manifest["skin_name"]
        _ensure_new_skin(project, name)
        try:
            with Image.open(io.BytesIO(body)) as image:
                if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("unsupported image format or image exceeds 40 million pixels")
                image.load()
                generated = ImageOps.exif_transpose(image).convert("RGBA")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError("could not decode the generated image") from exc
        original_size = list(generated.size)
        width, height = manifest["expected_size"]
        if abs((generated.width / generated.height) / (width / height) - 1) > 0.01:
            raise ValueError(f"image aspect ratio changed; regenerate the entire {width} x {height} canvas including padding")
        if generated.size != (width, height):
            generated = generated.resize((width, height), Image.Resampling.LANCZOS)
        x, y, w, h = manifest["content_rect"]
        layout = manifest["layout"]
        composite = generated.crop((x, y, x + w, y + h)).resize(
            (layout["composite_w"], layout["composite_h"]), Image.Resampling.LANCZOS
        )
        job_dir = _job_dir(project, job_id)
        # Build in an isolated attempt directory. Failed rebakes leave the
        # original project and any existing skins untouched and are retryable.
        attempt = job_dir / f"attempt-{uuid.uuid4().hex}"
        skin_dir = attempt / "skin"
        export_dir = attempt / "export"
        skin_dir.mkdir(parents=True)
        for filename in ("composite.png", "layout_map.json"):
            shutil.copy2(job_dir / name / filename, skin_dir / filename)
        composite.save(skin_dir / "reskinned_composite.png")
        finish_reskin(project.path, skin_dir, name, layout)
        rebake = rebake_skin(
            project, name, sam_provider=SAMProvider(base_url=""),
            segmentation_method="original", skin_dir=skin_dir, output_dir=export_dir,
        )
        final_dir = _inside(project.path, f".genie/skins/{name}")
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        _ensure_new_skin(project, name)
        exports = [(export_dir / rebake[key], project.path / rebake[key])
                   for key in ("atlas", "atlas_image", "skin_spine_json")]
        # Rewrite response paths before committing; no further image work is
        # necessary once the staged files become visible to the app.
        result = {
            "skin_name": name, "method": manifest["method"], "layout": layout,
            "composite": (final_dir / "composite.png").relative_to(project.path).as_posix(),
            "reskinned_composite": (final_dir / "reskinned_composite.png").relative_to(project.path).as_posix(),
        }
        if manifest["method"] == "atlas":
            for key in ("reskinned_snapshot", "reskinned_atlas"):
                result[key] = (final_dir / f"{key}.png").relative_to(project.path).as_posix()
        committed = []
        skin_committed = False
        try:
            for source, destination in exports:
                # Exclusive creation: even a concurrent legacy generate must
                # never be overwritten by a handoff import.
                with destination.open("xb") as out, source.open("rb") as inp:
                    committed.append(destination)
                    shutil.copyfileobj(inp, out)
            skin_dir.rename(final_dir)
            skin_committed = True
            manifest.update(
                status="imported", result=result, rebake=rebake,
                result_sha256=digest, imported_size=original_size,
                imported_at=datetime.now(timezone.utc).isoformat(),
            )
            _write_manifest(job_dir, manifest)
        except Exception:
            if skin_committed:
                final_dir.rename(skin_dir)
            for path in committed:
                path.unlink()
            raise
        return manifest
