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
import math
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brickfall import (  # noqa: E402
    CalendarParseError,
    calendar_from_json,
    calendar_to_json,
    coverage_errors,
    fetch_calendar,
    pieces_for_calendar,
    render_svg,
)

# Inclusive. 0 is the stable pack; any other value in range only reorders equal choices.
SEED_MIN = -2_147_483_648
SEED_MAX = 2_147_483_647

# GitHub login: 1-39 letters, digits, or single hyphens, not starting or ending with a hyphen.
_USERNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
_USERNAME_HINT = (
    "a GitHub login of 1-39 letters, digits, or single hyphens, "
    "not starting or ending with a hyphen (for example octocat)"
)


class InputError(ValueError):
    """An action input or CLI flag is missing or not usable."""


def fail(message: str) -> int:
    print(f"contrib-tetris: {message}", file=sys.stderr)
    return 1


def parse_seed(raw: object) -> int:
    """Return a packing seed, or raise InputError naming seed and the valid range."""
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise InputError(
            f"seed (--seed) is {raw!r}, which is not an integer from {SEED_MIN} to {SEED_MAX}. "
            "Use 0 for the stable pack, or another integer in that range."
        )
    if isinstance(raw, str):
        try:
            value = int(raw.strip())
        except ValueError:
            raise InputError(
                f"seed (--seed) is {raw!r}, which is not an integer from {SEED_MIN} to {SEED_MAX}. "
                "Use 0 for the stable pack, or another integer in that range."
            ) from None
    else:
        value = raw
    if value < SEED_MIN or value > SEED_MAX:
        raise InputError(
            f"seed (--seed) is {value}, which is outside {SEED_MIN} to {SEED_MAX}. "
            "Use 0 for the stable pack, or another integer in that range."
        )
    return value


def parse_speed(raw: object) -> float:
    """Return a positive animation multiplier, or raise InputError naming speed.

    1 keeps the normal pace. 2 plays twice as fast and 0.5 plays at half speed.
    """
    hint = "Use 1 for the normal pace, 2 to play twice as fast, or 0.5 to play at half speed."
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise InputError(f"speed (--speed) is {raw!r}, which is not a positive number. {hint}")
    if isinstance(raw, str):
        try:
            value = float(raw.strip())
        except ValueError:
            raise InputError(
                f"speed (--speed) is {raw!r}, which is not a positive number. {hint}"
            ) from None
    else:
        value = float(raw)
    if not math.isfinite(value) or value <= 0:
        raise InputError(f"speed (--speed) is {raw!r}, which is not a positive number. {hint}")
    return value


def checked_username(username: str | None, *, required: bool) -> str | None:
    """Return a usable login, or None when an optional override was omitted."""
    if username is None or username == "":
        if required:
            raise InputError(
                f"github_user_name (--username) is empty. Set it to {_USERNAME_HINT}."
            )
        return None
    if _USERNAME.fullmatch(username) is None:
        raise InputError(
            f"github_user_name (--username) is {username!r}, which is not a GitHub login. "
            f"Use {_USERNAME_HINT}."
        )
    return username


def _relative_paths_required() -> bool:
    # action.yml sets this so SVG paths stay inside the workspace. The CLI
    # leaves it unset and still accepts absolute paths.
    return os.environ.get("TETRIS_REQUIRE_RELATIVE") == "1"


def validate_output_path(raw: str, name: str, *, example: str, relative: bool) -> Path:
    """Return the SVG path to write, or raise InputError naming that input."""
    if raw.strip() == "":
        raise InputError(f"{name} is empty. Pass a file path ending in .svg, for example {example}.")
    if raw != raw.strip() or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise InputError(
            f"{name} is {raw!r}, which is not a valid file path. "
            "Pass a file path ending in .svg with no leading or trailing whitespace "
            f"and no control characters, for example {example}."
        )
    if raw.endswith(("/", "\\")):
        raise InputError(
            f"{name} is {raw!r}, which points at a directory. "
            f"Pass a file path ending in .svg, for example {example}."
        )
    path = Path(raw)
    if any(part == ".." for part in path.parts):
        raise InputError(
            f"{name} is {raw!r}, which must not contain '..'. "
            f"Pass a file path ending in .svg, for example {example}."
        )
    if path.suffix.lower() != ".svg":
        raise InputError(
            f"{name} is {raw!r}, which must be a file path ending in .svg, for example {example}."
        )
    if relative and path.is_absolute():
        raise InputError(
            f"{name} is {raw!r}, which must be relative to the workspace, not an absolute path. "
            f"Pass a file path ending in .svg, for example {example}."
        )
    return path


def _same_output(left: Path, right: Path) -> bool:
    def key(path: Path) -> tuple[str, ...]:
        return tuple(part for part in path.parts if part != ".")

    return key(left) == key(right)


def _checked_token(token: str | None) -> str:
    if token is None or token.strip() == "":
        raise InputError(
            "token (--token or $GITHUB_TOKEN) is empty. "
            "Pass a non-empty GitHub token that can read the contribution calendar. "
            "On the action, token defaults to the calling workflow's GITHUB_TOKEN."
        )
    if token != token.strip():
        raise InputError(
            "token (--token or $GITHUB_TOKEN) has leading or trailing whitespace. "
            "Pass a non-empty GitHub token with no spaces around it. "
            "On the action, token defaults to the calling workflow's GITHUB_TOKEN."
        )
    return token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a Tetris-style contribution calendar SVG.")
    parser.add_argument("--username", help="GitHub login whose calendar should be drawn")
    parser.add_argument("--token", help="GitHub token with access to the contribution calendar. Defaults to $GITHUB_TOKEN")
    parser.add_argument("--input", type=Path, help="Read a previously saved contributions JSON instead of calling the API")
    parser.add_argument(
        "--dump-json",
        type=Path,
        help=(
            "Write the normalized calendar JSON (count and integer level) to this path. "
            "That file can be passed back to --input"
        ),
    )
    parser.add_argument("--out", type=Path, help="Directory for tetris-contrib.svg and tetris-contrib-dark.svg")
    parser.add_argument("--light", help="Write the light SVG to this path")
    parser.add_argument("--dark", help="Write the dark SVG to this path")
    parser.add_argument(
        "--seed",
        default="0",
        help=(
            "Packing seed. An integer from -2147483648 to 2147483647. "
            "0 is the stable default; any other integer in that range reorders equal tetromino choices"
        ),
    )
    parser.add_argument(
        "--speed",
        default="1.0",
        help=(
            "Animation speed as a positive multiplier. "
            "1 is the normal pace; 2 plays twice as fast and 0.5 plays at half speed. "
            "The bricks and the resting calendar stay the same"
        ),
    )
    parser.add_argument("--print-stats", action="store_true", help="Print the piece inventory")
    args = parser.parse_args(argv)

    try:
        seed = parse_seed(args.seed)
        speed = parse_speed(args.speed)
        relative = _relative_paths_required()
        if args.light is not None or args.dark is not None:
            if args.light is None or args.dark is None:
                raise InputError(
                    "svg_light_path (--light) and svg_dark_path (--dark) must both be set. "
                    "For example --light dist/tetris-contrib.svg --dark dist/tetris-contrib-dark.svg."
                )
            light = validate_output_path(
                args.light,
                "svg_light_path (--light)",
                example="dist/tetris-contrib.svg",
                relative=relative,
            )
            dark = validate_output_path(
                args.dark,
                "svg_dark_path (--dark)",
                example="dist/tetris-contrib-dark.svg",
                relative=relative,
            )
            if _same_output(light, dark):
                raise InputError(
                    "svg_light_path (--light) and svg_dark_path (--dark) point at the same file "
                    f"({args.light!r} and {args.dark!r}). "
                    "Pass two different file paths ending in .svg, "
                    "for example dist/tetris-contrib.svg and dist/tetris-contrib-dark.svg."
                )
            outputs = {"light": light, "dark": dark}
        elif args.out:
            outputs = {
                "light": args.out / "tetris-contrib.svg",
                "dark": args.out / "tetris-contrib-dark.svg",
            }
        else:
            raise InputError(
                "pass an output directory with --out, or both svg_light_path (--light) and "
                "svg_dark_path (--dark). For example --out dist, or "
                "--light dist/tetris-contrib.svg --dark dist/tetris-contrib-dark.svg."
            )

        if args.input:
            username = checked_username(args.username, required=False)
            example = "Pass a contribution calendar JSON file, for example sample/contributions.json."
            try:
                raw_text = args.input.read_text(encoding="utf-8")
            except FileNotFoundError:
                raise InputError(f"--input {args.input} was not found. {example}") from None
            except IsADirectoryError:
                raise InputError(f"--input {args.input} is a directory. {example}") from None
            except UnicodeDecodeError:
                raise InputError(f"--input {args.input} is not UTF-8 text. {example}") from None
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                raise InputError(
                    f"--input {args.input} is not valid JSON ({exc.msg} on line {exc.lineno}). {example}"
                ) from None
            if isinstance(payload, dict) and username is not None:
                payload = {**payload, "username": username}
            calendar = calendar_from_json(payload)
        else:
            if args.username is None:
                username_raw = os.environ.get("GITHUB_USERNAME") or os.environ.get("GITHUB_ACTOR")
            else:
                # An explicit empty login must fail, not fall through to the actor.
                username_raw = args.username
            username = checked_username(username_raw, required=True)
            token = _checked_token(args.token or os.environ.get("GITHUB_TOKEN"))
            if username is None:
                raise InputError(
                    f"github_user_name (--username) is empty. Set it to {_USERNAME_HINT}."
                )
            calendar = fetch_calendar(username, token)
    except InputError as exc:
        return fail(str(exc))
    except CalendarParseError as exc:
        if args.input is not None:
            return fail(
                f"--input {args.input} is not a usable contribution calendar. {exc} "
                "Pass a file like sample/contributions.json."
            )
        return fail(f"the contribution calendar is not usable. {exc}")

    pieces = pieces_for_calendar(calendar, seed=seed)
    errors = coverage_errors(pieces, 7, calendar.columns)
    if errors:
        print("tiling failed:", "; ".join(errors[:8]), file=sys.stderr)
        return 1

    if args.dump_json:
        args.dump_json.parent.mkdir(parents=True, exist_ok=True)
        args.dump_json.write_text(json.dumps(calendar_to_json(calendar), indent=2) + "\n", encoding="utf-8")

    for theme, path in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        svg = render_svg(calendar, pieces, theme, speed=speed)
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
