#!/usr/bin/env python3
"""Generate falling-brick contribution SVGs.

Examples:
  python3 generate.py --username KenYanL --token "$GITHUB_TOKEN" --out dist
  python3 generate.py --input sample/contributions.json --out dist
  python3 generate.py --username KenYanL --token "$GITHUB_TOKEN" \\
      --light dist/tetris-contrib.svg --dark dist/tetris-contrib-dark.svg --seed 1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brickfall import (  # noqa: E402
    calendar_from_json,
    calendar_to_json,
    coverage_errors,
    fetch_calendar,
    pieces_for_calendar,
    render_svg,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a Tetris-style contribution calendar SVG.")
    parser.add_argument("--username", help="GitHub login whose calendar should be drawn")
    parser.add_argument("--token", help="GitHub token with access to the contribution calendar. Defaults to $GITHUB_TOKEN")
    parser.add_argument("--input", type=Path, help="Read a previously saved contributions JSON instead of calling the API")
    parser.add_argument("--dump-json", type=Path, help="Write the normalized calendar JSON to this path")
    parser.add_argument("--out", type=Path, help="Directory for tetris-contrib.svg and tetris-contrib-dark.svg")
    parser.add_argument("--light", type=Path, help="Write the light SVG to this path")
    parser.add_argument("--dark", type=Path, help="Write the dark SVG to this path")
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Packing seed. 0 is the stable default; any other integer reorders equal tetromino choices",
    )
    parser.add_argument("--print-stats", action="store_true", help="Print the piece inventory")
    args = parser.parse_args(argv)

    if args.light or args.dark:
        if args.light is None or args.dark is None:
            parser.error("pass both --light and --dark")
        outputs = {"light": args.light, "dark": args.dark}
    elif args.out:
        outputs = {
            "light": args.out / "tetris-contrib.svg",
            "dark": args.out / "tetris-contrib-dark.svg",
        }
    else:
        parser.error("pass --out, or both --light and --dark")

    if args.input:
        calendar = calendar_from_json(json.loads(args.input.read_text(encoding="utf-8")))
        if args.username:
            calendar = calendar_from_json(
                {**json.loads(args.input.read_text(encoding="utf-8")), "username": args.username}
            )
    else:
        import os

        username = args.username or os.environ.get("GITHUB_USERNAME") or os.environ.get("GITHUB_ACTOR")
        token = args.token or os.environ.get("GITHUB_TOKEN")
        if not username or not token:
            parser.error("provide --input, or --username and a token (--token or $GITHUB_TOKEN)")
        calendar = fetch_calendar(username, token)

    pieces = pieces_for_calendar(calendar, seed=args.seed)
    errors = coverage_errors(pieces, 7, calendar.columns)
    if errors:
        print("tiling failed:", "; ".join(errors[:8]), file=sys.stderr)
        return 1

    if args.dump_json:
        args.dump_json.parent.mkdir(parents=True, exist_ok=True)
        args.dump_json.write_text(json.dumps(calendar_to_json(calendar), indent=2) + "\n", encoding="utf-8")

    for theme, path in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        svg = render_svg(calendar, pieces, theme)
        path.write_text(svg, encoding="utf-8")
        print(f"{path} {len(svg.encode())} bytes")

    if args.print_stats:
        counts: dict[str, int] = {}
        for piece in pieces:
            counts[piece.name] = counts.get(piece.name, 0) + 1
        covered = sum(piece.size for piece in pieces)
        small = sum(piece.size for piece in pieces if piece.size < 4)
        print(
            f"{calendar.username} {calendar.start.isoformat()}..{calendar.end.isoformat()} "
            f"total={calendar.total} cells={covered} pieces={len(pieces)} "
            f"leftover_cells={small}"
        )
        print(" ".join(f"{name}={counts[name]}" for name in sorted(counts)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
