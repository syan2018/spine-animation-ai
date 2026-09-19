#!/usr/bin/env python3
"""Export a Spine 4.2 region rig to an editable native Godot 4 project."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reskin-app"))
from app.backend.godot.exporter import export_spine
from app.backend.godot.spine_import import UnsupportedSpine, inspect_spine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spine", type=Path, required=True, help="Exact Spine JSON, not its folder")
    parser.add_argument("--atlas", type=Path, help="Defaults to the JSON basename + .atlas")
    parser.add_argument("--output", type=Path, help="New output directory; never overwritten")
    parser.add_argument("--skin-json", type=Path, action="append", default=[], help="Additional generated skin JSON with matching .atlas")
    parser.add_argument("--skin", default="default", help="Initial displayed skin")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--loops", help="Comma-separated loop names; default idle,walk,run; empty disables looping")
    parser.add_argument("--check", action="store_true", help="Report skeleton capabilities without writing files")
    args = parser.parse_args()
    try:
        if args.check:
            issues = inspect_spine(json.loads(args.spine.read_text(encoding="utf-8")))
            print(json.dumps({"supported": not issues, "unsupported": issues}, indent=2))
            return 2 if issues else 0
        if args.output is None:
            parser.error("--output is required unless --check is used")
        report = export_spine(args.spine, args.output, atlas_path=args.atlas,
                              extra_skins=args.skin_json, initial_skin=args.skin, fps=args.fps,
                              loops=None if args.loops is None else set(filter(None, args.loops.split(","))))
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except UnsupportedSpine as exc:
        print(json.dumps({"status": "unsupported", "unsupported": exc.issues}, indent=2), file=sys.stderr)
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
