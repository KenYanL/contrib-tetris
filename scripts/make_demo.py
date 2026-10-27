#!/usr/bin/env python3
"""Rebuild the synthetic README demo from a fixed seed.

Writes demo/contributions.json, then renders demo/tetris-contrib.svg and
demo/tetris-contrib-dark.svg with generate.py. The calendar is not anyone's
real contribution history. ``--out`` writes that same trio somewhere else
and leaves the committed demo alone.

    python3 scripts/make_demo.py
    python3 scripts/make_demo.py --out /tmp/brickfall-demo
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brickfall import LEVEL_NAMES, Calendar, Day, calendar_from_days, profile_window  # noqa: E402
from generate import main as generate_main  # noqa: E402

# Inverse of brickfall.LEVEL_NAMES. generate.py reads contributionLevel
# (NONE / FIRST_QUARTILE / ...), the enum the GitHub API returns. An integer
# "level" field is ignored and every day is treated as empty.
_LEVEL_NAME = {value: name for name, value in LEVEL_NAMES.items()}

# Same seed always rebuilds the same calendar and the same SVGs.
SEED = 20261023
USERNAME = "demo"
# Pins the profile window so a later run does not slide the year forward.
AS_OF = date(2026, 10, 17)
# 0 is the renderer's stable pack.
PACK_SEED = 0

# Weekly mode: 0 vacation, 1 light, 2 normal, 3 crunch.
# Rows persist, so busy weeks and quiet weeks clump the way a real graph does.
_TRANSITIONS = {
    0: (0.45, 0.40, 0.15, 0.00),
    1: (0.10, 0.50, 0.35, 0.05),
    2: (0.06, 0.22, 0.57, 0.15),
    3: (0.08, 0.12, 0.50, 0.30),
}


def _pick(rng: random.Random, weights: tuple[float, ...]) -> int:
    roll = rng.random()
    total = 0.0
    for index, weight in enumerate(weights):
        total += weight
        if roll <= total:
            return index
    return len(weights) - 1


def _count_for(rng: random.Random, mode: int, weekend: bool) -> int:
    if mode == 0:
        chance = 0.04 if weekend else 0.12
    elif mode == 1:
        chance = 0.08 if weekend else 0.48
    elif mode == 2:
        chance = 0.18 if weekend else 0.78
    else:
        chance = 0.40 if weekend else 0.94
    if rng.random() > chance:
        return 0
    if mode == 0:
        count = 1
    elif mode == 1:
        count = rng.choice((1, 1, 1, 2, 2, 3))
    elif mode == 2:
        roll = rng.random()
        if roll < 0.45:
            count = rng.randint(1, 3)
        elif roll < 0.80:
            count = rng.randint(4, 7)
        elif roll < 0.95:
            count = rng.randint(8, 12)
        else:
            count = rng.randint(13, 18)
    else:
        roll = rng.random()
        if roll < 0.25:
            count = rng.randint(3, 6)
        elif roll < 0.70:
            count = rng.randint(7, 12)
        else:
            count = rng.randint(13, 22)
    if weekend and count > 1:
        return max(1, count // 2)
    return count


def _levels(counts: list[int]) -> list[int]:
    """GitHub-style quartiles of the days that have any activity."""
    positive = sorted(count for count in counts if count > 0)
    if not positive:
        return [0 for _ in counts]

    def quartile(fraction: float) -> int:
        index = min(len(positive) - 1, max(0, math.ceil(fraction * len(positive)) - 1))
        return positive[index]

    q1, q2, q3 = quartile(0.25), quartile(0.50), quartile(0.75)
    levels: list[int] = []
    for count in counts:
        if count <= 0:
            levels.append(0)
        elif count <= q1:
            levels.append(1)
        elif count <= q2:
            levels.append(2)
        elif count <= q3:
            levels.append(3)
        else:
            levels.append(4)
    return levels


def calendar_payload(calendar: Calendar) -> dict:
    """Calendar JSON in the shape ``generate.py --input`` parses.

    Days use ``contributionCount`` and ``contributionLevel`` so the loader
    keeps the quartile colors. ``calendar_to_json`` writes ``count`` and
    integer ``level``, and the level is dropped on read.
    """
    return {
        "username": calendar.username,
        "total": calendar.total,
        "start": calendar.start.isoformat(),
        "end": calendar.end.isoformat(),
        "weeks": [
            [
                {
                    "date": day.date.isoformat(),
                    "contributionCount": day.count,
                    "contributionLevel": _LEVEL_NAME[day.level],
                }
                for day in week
            ]
            for week in calendar.weeks
        ],
    }


def synthetic_calendar():
    rng = random.Random(SEED)
    start, end = profile_window(AS_OF)
    mode = 2
    counts: list[int] = []
    day = start
    while day <= end:
        if (day - start).days % 7 == 0:
            mode = _pick(rng, _TRANSITIONS[mode])
        counts.append(_count_for(rng, mode, weekend=day.weekday() >= 5))
        day += timedelta(days=1)
    levels = _levels(counts)
    days = [Day(start + timedelta(days=index), count, level) for index, (count, level) in enumerate(zip(counts, levels))]
    return calendar_from_days(USERNAME, start, end, days)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild the synthetic README demo from a fixed seed.")
    parser.add_argument(
        "--out",
        type=Path,
        help="Directory for contributions.json and the two SVGs. Defaults to demo/.",
    )
    args = parser.parse_args(argv)
    calendar = synthetic_calendar()
    demo = ROOT / "demo" if args.out is None else args.out
    demo.mkdir(parents=True, exist_ok=True)
    payload = demo / "contributions.json"
    payload.write_text(json.dumps(calendar_payload(calendar), indent=2) + "\n", encoding="utf-8")
    code = generate_main(
        [
            "--input",
            str(payload),
            "--out",
            str(demo),
            "--seed",
            str(PACK_SEED),
            "--print-stats",
        ]
    )
    if code != 0:
        return code
    print(
        f"demo seed={SEED} days={sum(len(week) for week in calendar.weeks)} "
        f"active={sum(day.count > 0 for week in calendar.weeks for day in week)} "
        f"total={calendar.total}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
