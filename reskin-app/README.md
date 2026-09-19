# Genie Spine Reskin

AI-powered reskinning for Spine 2D character projects. Loads an existing Spine
rig and renders the character via the live `spine-pixi-v8` runtime. Generate an
image in Codex and import it with the original part masks, or use the existing
Gemini API generation and remote segmentation pipeline. Both routes build a
new skin for the original rig.

## What you get

- **Open project** — point at a folder containing `Spine.json` + `*.atlas` +
  `*.png`. The rig renders in a PixiJS canvas with the original skin.
- **Codex workflow** — prepare an image task, generate inside Codex, and import
  the result without an image API key in the app. See [Generate in Codex](#generate-in-codex).
- **Gemini API generation** — describe the look (`emerald and silver royal robes`)
  and click Generate. The legacy pipeline:
    1. Snapshots the live canvas as a clean static reference.
    2. Pads the snapshot to Gemini's nearest supported aspect ratio so the
       output maps 1:1 back to input pixels.
    3. Sends to Gemini Nano Banana for the global reskin.
    4. Crops back to the original dimensions.
    5. Computes per-slot bboxes by toggling slot visibility on the live spine
       instance.
    6. Calls the SAM-3 server (one HTTP call) with all bboxes; receives one
       precise mask per slot.
    7. Repacks a per-skin atlas + writes a per-skin `Spine-{skin}.json` with
       the new skin entry.
    8. The canvas reloads spine-pixi against the per-skin atlas → the rigged
       character renders with the AI-reskinned per-slot textures.
- **Mask editor** — brush, eraser, lasso, and SAM-powered Magic Select for
  refining any slot's mask after the fact.
- **AI Terminal** — per-slot inpainting. Pick a slot, type a prompt, Gemini
  redraws just that part preserving the silhouette.
- **Per-slot edits** — non-destructive HSL/RGB/contrast/transform sliders.
- **Export** — writes the new skin's atlas + per-skin Spine JSON next to your
  original project so you can open it in Spine 2D.

## Project layout

```
app/
├── backend/          FastAPI server
│   ├── server.py     Routes for project, reskin, mask, export
│   ├── projects.py   Project model + open logic
│   ├── ai/           Gemini provider + SAM provider
│   ├── reskin/       compose / slice / pipeline
│   ├── spine/        parser, skin_writer, atlas_repack
│   └── imaging.py    HSL/RGB/transform for per-slot edits
└── frontend/         Vite + React + TypeScript + spine-pixi-v8
    ├── src/components/
    │   ├── canvas/SpineCanvas.tsx       Live rig render
    │   ├── Sidebar.tsx                   Slot list + visibility/lock
    │   ├── right-panel/PartEditor.tsx   Edits + AI Terminal + Mask launcher
    │   └── modals/                       New skin / AI Terminal / Mask
    └── src/styles/
        ├── genie-tokens.css   ← design system tokens (do not edit)
        └── index.css

design-system/genie-studio/  — design tokens, icons, brand mark, README

scripts/
├── explode_spine_atlas.py   Ingests a packed Spine atlas → per-region PNGs
└── make_atlas.py             Row-based bin packer (used by atlas_repack)
```

## Setup

### Requirements

- Python 3.9+ (3.10+ recommended)
- Node 18+
- For the in-app Gemini generation mode: a Gemini API key (`GEMINI_API_KEY`)
- For remote segmentation: a SAM server (`SAM_SERVER_URL`) or Bria (`FAL_KEY`)
- The Codex workflow below prepares and imports locally without any of these keys
- Optional: an Anthropic API key for the chat sidebar (`ANTHROPIC_API_KEY`)

### Env vars

Copy `app/.env.example` to `app/.env` and fill in:

```
GEMINI_API_KEY=...
SAM_SERVER_URL=http://your-sam-host:30231
ANTHROPIC_API_KEY=...
```

### Install + run

```bash
# Backend
cd app/backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.backend.server:app --host 127.0.0.1 --port 8765 --app-dir ../..

# Frontend (separate terminal)
cd app/frontend
npm install
npm run dev
```

Open http://localhost:5173.

From the repository root on Windows (PowerShell):

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r reskin-app/app/backend/requirements.txt
.venv/Scripts/python.exe -m uvicorn app.backend.server:app --host 127.0.0.1 --port 8765 --app-dir reskin-app
```

In a second terminal, run `npm ci` and `npm run dev` from
`reskin-app/app/frontend`. Keep the backend bound to localhost; the existing app
is a local single-project tool, not an authenticated multi-user service.

## Generate in Codex

This mode hands image editing to Codex's built-in image tool, then imports the
result into the same rig. The app does not call OpenAI's paid Image API and does
not expose a proxy for subscription credentials. Availability and usage limits
of the built-in tool are controlled by your Codex session; the app cannot force
a particular GPT Image model.

1. Open a character in Reskin Studio and click **Generate**.
2. Choose **Codex workflow**, enter a prompt and a new look name, then click
   **Prepare for Codex**. Atlas mode captures the current character; exploded
   mode requires loose part PNGs.
3. Click **Copy request** and send it in Codex with this repository open. The
   repository skill `$reskin-in-codex` reads the saved task and its images,
   generates the edit using the built-in image tool, and submits the saved image.
4. The task panel detects an imported result automatically. Review the preview
   and click **Accept** to show the skin on the rig. Existing export controls
   continue to work.

You can also choose the saved generated image with **Import image**. Tasks
persist under `<project>/.genie/handoffs/<id>/`; reopen **Generate** to resume one.
If Codex has not discovered the new skill yet, start a new session in the repo
or explicitly point it at `.agents/skills/reskin-in-codex/SKILL.md`.

The importer preserves original alpha masks, including soft edges, and makes no
SAM or Bria calls. This is intended for **surface/style changes with the same
silhouette**. Adding wings, changing limb lengths or moving parts needs a new
layout/rig. The app validates file format, size, aspect ratio and source asset
hashes; Codex/user visual review is still needed to catch geometry drift.
This uses the app's existing single-page atlas and region-part pipeline; it is
not a general converter for arbitrary Spine mesh, clipping or multi-attachment
assets. The handoff produces Spine JSON and atlas files. Use the native Godot
export below to convert a supported rig after importing.

### Export to Godot

Choose **Export → Godot 4 · native cutout**. The app creates a new standalone
Godot project containing a `Skeleton2D`/`Bone2D` rig, `Sprite2D` parts, an
`AnimationPlayer` with editable animation resources, and skin-switching support.
It includes saved part transforms, current visibility, and pending image edits
for the selected active look. Unsupported Spine features produce an explicit
report instead of being discarded. Existing Spine export remains selectable.

Copy the returned `project.godot` path into Godot's project manager and run the
preview. See [native Godot export](../docs/godot-native-export.md) for CLI usage,
game integration, capabilities and real-engine verification.

### Local CLI

From the repository root, with the backend running (use `.venv/Scripts/python.exe`
in place of `python` on Windows if needed):

```text
python scripts/codex_reskin.py prepare --project "path/to/character" --skin emerald --prompt "Emerald robes with silver trim" --method exploded
python scripts/codex_reskin.py status --manifest "path/to/manifest.json"
python scripts/codex_reskin.py import --manifest "path/to/manifest.json" --image "path/to/generated.png"
```

For atlas preparation outside the UI, use `--method atlas --snapshot pose.png`.
`--url http://127.0.0.1:8765` can be passed before the subcommand. The CLI uses
only Python's standard library and returns JSON. The import command performs
the local slice/repack step; do not call the legacy `/api/reskin/rebake` after it,
as that endpoint uses the configured remote segmentation method.

### App API contract

All routes operate on the project opened via `POST /api/project/open`.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/reskin/handoffs` | Prepare with JSON `{skin_name, prompt, method}`; method defaults to `exploded` |
| `GET /api/reskin/handoffs` | List saved tasks for this character as `{jobs: [...]}` |
| `GET /api/reskin/handoffs/{id}` | Read task state, ordered input paths, prompt and result |
| `POST /api/reskin/handoffs/{id}/result` | Upload PNG/JPEG/WebP bytes; validate, restore layout and build a new skin locally |

A prepared task returns `id`, `status: prepared`, `manifest_path`, ordered
`input_images`, `prompt`, `expected_size` and the original layout. A successful
import returns `status: imported`, `result` (the existing preview response),
and `rebake` with `mask_method: original` and output filenames.

Images are limited to 25 MiB and 40 million decoded pixels. Keep the entire
prepared canvas, including padding. A different resolution with the same aspect
ratio is normalized; an aspect ratio difference over 1% is rejected. Do not crop
to just the character or just the atlas. Original assets changing after prepare
causes a conflict. Existing skins are never replaced. Retrying the same uploaded
bytes is idempotent; another variation needs a new task/name. Failed builds stay
in the task's staging directory and do not publish a skin.

### Checks

```text
python -m pip install -r reskin-app/requirements-dev.txt
python -m pytest reskin-app/tests -q
```

Run `npm run build` from `app/frontend`. Backend tests use synthetic image
responses and forbid external AI calls; they do not measure model output quality.

### Ingesting a Spine project

If your Spine project uses an old `bounds:`-style atlas (e.g. exports from
older tools), run the explode script once to produce a standard Spine 4.x
atlas plus per-region PNGs:

```bash
python scripts/explode_spine_atlas.py \
  --char-dir /path/to/CharacterFolder \
  --base-name CharacterAtlasBaseName \
  --output-dir /wherever/you/want/the/genie-project
```

Open the output dir in the app.

### Magic Select

To enable SAM-based magic select in the mask editor, drop the SAM ONNX
decoder file at:

```
app/frontend/public/magic_cut.onnx
```

The frontend probes it at runtime; if it's missing, magic select shows a
clear hint and the other tools still work.

## Design system

This project uses the Genie Studio design system at
`design-system/genie-studio/`. Read `CLAUDE.md` and the design system's
`README.md` before touching any UI — never invent colors, type, spacing, or
components not grounded in the system.
