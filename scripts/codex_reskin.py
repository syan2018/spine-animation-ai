#!/usr/bin/env python3
"""Prepare, inspect and import Reskin Studio image tasks without API keys.

Run the local app backend first. This client only talks to that backend;
image generation is performed separately by Codex's built-in image tool.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request(base: str, path: str, *, data=None, image: bytes | None = None):
    body = image if image is not None else json.dumps(data).encode("utf-8") if data is not None else None
    content_type = "application/octet-stream" if image is not None else "application/json"
    req = Request(base.rstrip("/") + path, data=body, headers={"Content-Type": content_type})
    with urlopen(req, timeout=180) as response:
        return json.load(response)


def open_project(base: str, path: str) -> dict:
    current = request(base, "/api/project/status")
    if current.get("open") and Path(current["path"]).resolve() == Path(path).resolve():
        return current
    return request(base, "/api/project/open", data={"path": str(Path(path).resolve())})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765", help="Local Reskin Studio backend URL")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Build an image task without generating")
    prepare.add_argument("--project", required=True, help="Spine project folder")
    prepare.add_argument("--skin", required=True, help="New look name, e.g. emerald-robes")
    prepare.add_argument("--prompt", required=True)
    prepare.add_argument("--method", choices=("exploded", "atlas"), default="exploded")
    prepare.add_argument("--snapshot", type=Path, help="Rendered reference PNG; required for atlas mode")
    for command in ("status", "import"):
        sub = commands.add_parser(command, help="Read a task" if command == "status" else "Import a generated image and build the skin locally")
        sub.add_argument("--manifest", type=Path, required=True, help="manifest.json from a prepared task")
        if command == "import":
            sub.add_argument("--image", type=Path, required=True, help="Saved image from the Codex image tool")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            open_project(args.url, args.project)
            if args.method == "atlas":
                if not args.snapshot:
                    parser.error("atlas mode requires --snapshot (or prepare the task in the app)")
                from urllib.parse import urlencode
                request(args.url, "/api/project/snapshot?" + urlencode({"skin_name": args.skin}), image=args.snapshot.read_bytes())
            result = request(args.url, "/api/reskin/handoffs", data={
                "skin_name": args.skin, "prompt": args.prompt, "method": args.method,
            })
        else:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            open_project(args.url, manifest["project_path"])
            from urllib.parse import quote
            path = "/api/reskin/handoffs/" + quote(manifest["id"], safe="")
            if args.command == "import":
                if args.image.stat().st_size > 25 * 1024 * 1024:
                    raise ValueError("image exceeds 25 MiB")
                result = request(args.url, path + "/result", image=args.image.read_bytes())
            else:
                result = request(args.url, path)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except HTTPError as exc:
        print(f"Reskin Studio returned {exc.code}: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
    except URLError as exc:
        print(f"Cannot reach Reskin Studio at {args.url}. Start the backend first. {exc.reason}", file=sys.stderr)
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
