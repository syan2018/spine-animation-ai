"""Contract and round-trip tests. All external AI calls are forbidden."""
import asyncio
import io
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.backend import projects, server, settings
from app.backend.ai.gemini import GeminiProvider
from app.backend.ai.sam_provider import SAMProvider
from app.backend.reskin import handoff
from app.backend.reskin.pipeline import full_reskin
from app.backend.spine.atlas_repack import repack_atlas


@pytest.fixture
def project(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("external AI must not be called by the handoff workflow")
    monkeypatch.setattr(GeminiProvider, "_get_client", no_network)
    monkeypatch.setattr(SAMProvider, "segment_with_bboxes", no_network)
    monkeypatch.setattr(handoff, "SAMProvider", lambda **kwargs: SAMProvider(base_url="https://not-called.invalid"))
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(settings, "REFERENCE_IMAGE_PATH", tmp_path / "reference.png")
    # Even if the user's normal segmentation requires a paid service, this
    # workflow explicitly chooses original alpha and must not call it.
    settings.save_settings(settings.Settings(segmentation=settings.SegmentationSettings(method="bg_components")))
    from app.backend.ai.cc_segment import ComponentSegmenter
    monkeypatch.setattr(ComponentSegmenter, "segment_with_bboxes", no_network)
    folder = tmp_path / "character"
    folder.mkdir()
    image = Image.new("RGBA", (20, 32), (20, 120, 220, 255))
    image.putpixel((0, 0), (0, 0, 0, 0))
    image.putpixel((1, 0), (20, 120, 220, 77))
    image.save(folder / "head.png")
    repack_atlas(folder, folder, "Spine")
    spine = {
        "skeleton": {"spine": "4.2.0", "width": 20, "height": 32},
        "bones": [{"name": "root"}],
        "slots": [{"name": "head", "bone": "root", "attachment": "head"}],
        "skins": [{"name": "default", "attachments": {"head": {"head": {
            "width": 20, "height": 32, "scaleX": -1.5, "x": 5,
        }}}}],
        "animations": {"idle": {"bones": {"root": {"rotate": [{"value": 0}, {"time": 1, "value": 5}]}}}},
    }
    (folder / "Spine.json").write_text(json.dumps(spine), encoding="utf-8")
    p = projects.open_project(folder)
    (p.workdir / "snapshots").mkdir()
    image.save(p.workdir / "snapshots" / "green.png")
    return p


@pytest.fixture
def client(project, monkeypatch):
    monkeypatch.setattr(server._State, "project", project)
    return TestClient(server.app)


def prepare(client, mode="atlas", name="green"):
    response = client.post("/api/reskin/handoffs", json={"skin_name": name, "prompt": "Green silk", "method": mode})
    assert response.status_code == 200, response.text
    return response.json()


def image_bytes(size, color="green"):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


@pytest.mark.parametrize("mode", ["atlas", "exploded"])
def test_round_trip_preserves_rig_alpha_and_can_reopen(client, project, mode):
    original = project.spine_json_path.read_bytes()
    job = prepare(client, mode)
    assert Path(job["manifest_path"]).is_file()
    assert len(job["input_images"]) == 1
    assert job["status"] == "prepared"
    # Simulate the image tool with a differently sized, same-ratio canvas.
    body = image_bytes(tuple(n // 2 for n in job["expected_size"]))
    result = client.post(f"/api/reskin/handoffs/{job['id']}/result", content=body)
    assert result.status_code == 200, result.text
    imported = result.json()
    assert imported["status"] == "imported"
    assert imported["rebake"]["mask_method"] == "original"
    assert imported["rebake"]["sam_used"] is False
    exported = json.loads((project.path / imported["rebake"]["skin_spine_json"]).read_text())
    assert exported["bones"] == project.spine_json["bones"]
    assert exported["animations"] == project.spine_json["animations"]
    assert exported["skins"][0] == project.spine_json["skins"][0]
    assert exported["skins"][1]["attachments"]["head"]["head"]["scaleX"] == -1.5
    assert project.spine_json_path.read_bytes() == original
    with Image.open(project.path / "head.png") as src, Image.open(project.workdir / "skins/green/extracted/head.png") as dst:
        assert dst.size == src.size
        assert dst.getchannel("A").tobytes() == src.getchannel("A").tobytes()
    for key in ("composite", "reskinned_composite"):
        assert client.get("/api/project/file/" + imported["result"][key]).status_code == 200
    again = client.post(f"/api/reskin/handoffs/{job['id']}/result", content=body)
    assert again.status_code == 200 and again.json() == imported
    changed = client.post(f"/api/reskin/handoffs/{job['id']}/result", content=image_bytes(job["expected_size"], "blue"))
    assert changed.status_code == 409
    assert client.post("/api/project/open", json={"path": str(project.path)}).status_code == 200
    assert client.get(f"/api/reskin/handoffs/{job['id']}").json()["status"] == "imported"


@pytest.mark.parametrize("name", ["../outside", "..\\outside", "default", "con", "a/b", "", "A" * 49])
def test_invalid_skin_names_do_not_write(client, project, name):
    response = client.post("/api/reskin/handoffs", json={"skin_name": name, "prompt": "test"})
    assert response.status_code == 400
    assert not (project.workdir / "handoffs").exists()


def test_changed_source_rejected(client, project):
    job = prepare(client)
    Image.new("RGBA", (20, 32), "red").save(project.path / "head.png")
    response = client.post(f"/api/reskin/handoffs/{job['id']}/result", content=image_bytes(job["expected_size"]))
    assert response.status_code == 409
    assert not (project.workdir / "skins/green").exists()


def test_invalid_images_and_missing_jobs(client, project):
    job = prepare(client)
    for body in (b"", b"not an image", image_bytes((200, 50))):
        response = client.post(f"/api/reskin/handoffs/{job['id']}/result", content=body)
        assert response.status_code == 400
    assert client.get("/api/reskin/handoffs/not-an-id").status_code == 400
    assert client.get("/api/reskin/handoffs/" + "0" * 32).status_code == 404
    assert not (project.workdir / "skins/green").exists()


def test_failed_build_is_retryable_and_does_not_publish(client, project, monkeypatch):
    job = prepare(client)
    real_rebake = handoff.rebake_skin
    def fail(*args, **kwargs):
        raise ValueError("fixture build failure")
    monkeypatch.setattr(handoff, "rebake_skin", fail)
    body = image_bytes(job["expected_size"])
    response = client.post(f"/api/reskin/handoffs/{job['id']}/result", content=body)
    assert response.status_code == 400
    assert not (project.path / "Spine-green.json").exists()
    assert not (project.workdir / "skins/green").exists()
    assert client.get(f"/api/reskin/handoffs/{job['id']}").json()["status"] == "prepared"
    monkeypatch.setattr(handoff, "rebake_skin", real_rebake)
    assert client.post(f"/api/reskin/handoffs/{job['id']}/result", content=body).status_code == 200


def test_import_never_overwrites_existing_export(client, project):
    job = prepare(client)
    output = project.path / "Spine-green.png"
    output.write_bytes(b"existing output")
    response = client.post(f"/api/reskin/handoffs/{job['id']}/result", content=image_bytes(job["expected_size"]))
    assert response.status_code == 409
    assert output.read_bytes() == b"existing output"


def test_style_reference_and_job_survive_reload(client, project):
    Image.new("RGB", (16, 16), "blue").save(settings.REFERENCE_IMAGE_PATH)
    config = settings.load_settings()
    config.reference.enabled = True
    settings.save_settings(config)
    job = prepare(client)
    assert len(job["input_images"]) == 2
    assert Path(job["input_images"][0]).name == "style-reference.png"
    assert "FIRST input image" in job["prompt"]
    assert client.get("/api/reskin/handoffs").json()["jobs"][0]["id"] == job["id"]
    assert client.post("/api/project/open", json={"path": str(project.path)}).status_code == 200
    assert client.get(f"/api/reskin/handoffs/{job['id']}").json() == job


@pytest.mark.parametrize("mode", ["atlas", "exploded"])
def test_existing_provider_pipeline_still_finishes(project, mode):
    class FakeProvider:
        async def edit_image(self, image_path, prompt, *, out_path, **kwargs):
            with Image.open(image_path) as image:
                image.save(out_path)
            return out_path
    result = asyncio.run(full_reskin(
        project.path, project.workdir / "skins", "green", "green silk",
        image_provider=FakeProvider(), method=mode,
        atlas_path=project.path / "Spine.atlas", atlas_sheet_path=project.path / "Spine.png",
    ))
    assert (project.path / result["reskinned_composite"]).is_file()
    assert result["method"] == mode
    if mode == "atlas":
        with Image.open(project.path / result["reskinned_atlas"]) as output, Image.open(project.path / "Spine.png") as original:
            assert output.size == original.size
