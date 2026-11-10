"""Unit tests for the brick calendar packer and SVG timeline."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate  # noqa: E402
from generate import (  # noqa: E402
    InputError,
    checked_username,
    parse_palette,
    parse_seed,
    parse_speed,
    validate_input_path,
    validate_output_path,
)
from brickfall import (  # noqa: E402
    AUTO_HOLIDAYS,
    CHRISTMAS_PALETTES,
    HALLOWEEN_PALETTES,
    LUNAR_NEW_YEAR_DATES,
    LUNAR_NEW_YEAR_PALETTES,
    LUNAR_NEW_YEAR_SPAN_DAYS,
    NEWYEAR_PALETTES,
    VALENTINE_DAY,
    VALENTINE_PALETTES,
    ORIENTATIONS,
    PALETTE_CATALOG,
    PALETTE_NAMES,
    PALETTE_TABLES,
    PALETTES,
    PaletteTransition,
    AUTO_TRANSITIONS_DATES,
    AUTO_TRANSITIONS_DAYS,
    SMALL_PIECES,
    TETROMINOES,
    Calendar,
    CalendarParseError,
    Day,
    GraphQLError,
    PaletteSpec,
    _graphql,
    _validate_palette_catalog,
    calendar_from_json,
    calendar_to_json,
    coverage_errors,
    decompose,
    format_auto_dates,
    format_auto_days,
    palette_cli_help,
    palette_hint,
    QUERY,
    QUERY_DEFAULT,
    fetch_calendar,
    lands_before,
    make_timeline,
    match_shape,
    pieces_for_calendar,
    profile_window,
    range_exceeds_one_year,
    render_svg,
    resolve_palette,
    rotations,
    stack_order,
)


ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT / "sample" / "contributions.json"


def _connected(cells) -> bool:
    remaining = set(cells)
    start = remaining.pop()
    seen = {start}
    stack = [start]
    while stack:
        row, col = stack.pop()
        for neighbor in ((row + 1, col), (row - 1, col), (row, col + 1), (row, col - 1)):
            if neighbor in remaining and neighbor not in seen:
                remaining.remove(neighbor)
                seen.add(neighbor)
                stack.append(neighbor)
    return not remaining


class ShapeTests(unittest.TestCase):
    def test_catalog_rotations_are_connected_and_unique(self) -> None:
        expected = {"I": 2, "O": 1, "T": 4, "S": 2, "Z": 2, "J": 4, "L": 4, "I3": 2, "L3": 4, "I2": 2, "I1": 1}
        for name, shape in {**TETROMINOES, **SMALL_PIECES}.items():
            turns = rotations(shape)
            self.assertEqual(len(turns), expected[name], name)
            for turn in turns:
                self.assertEqual(len(turn), len(shape))
                self.assertTrue(_connected(turn), (name, turn))
                self.assertEqual(match_shape(turn), name)

    def test_orientations_cover_every_catalog_name(self) -> None:
        names = {name for name, _shape in ORIENTATIONS}
        self.assertEqual(names, set(expected_names()))


def expected_names():
    return set(TETROMINOES) | set(SMALL_PIECES)


class PackTests(unittest.TestCase):
    def test_rectangle_is_covered_by_real_pieces(self) -> None:
        pieces = decompose(7, 53)
        errors = coverage_errors(pieces, 7, 53)
        self.assertEqual(errors, [])
        leftover = sum(piece.size for piece in pieces if piece.size < 4)
        # 53*7 = 371 = 4*92 + 3, so a perfect pack leaves exactly 3 cells.
        self.assertEqual(leftover, 3)
        names = {piece.name for piece in pieces if piece.size == 4}
        self.assertGreaterEqual(len(names), 4)

    def test_pack_is_deterministic(self) -> None:
        first = decompose(7, 53)
        second = decompose(7, 53)
        self.assertEqual(first, second)

    def test_seed_zero_matches_the_stable_pack(self) -> None:
        self.assertEqual(decompose(7, 53), decompose(7, 53, seed=0))
        self.assertEqual(decompose(1, 4), decompose(1, 4, seed=0))

    def test_other_seeds_stay_valid_and_deterministic(self) -> None:
        baseline = decompose(7, 53)
        differed = False
        for seed in (1, 7, 19):
            first = decompose(7, 53, seed=seed)
            second = decompose(7, 53, seed=seed)
            self.assertEqual(first, second)
            self.assertEqual(coverage_errors(first, 7, 53), [])
            self.assertEqual(sum(piece.size for piece in first if piece.size < 4), 3)
            differed = differed or first != baseline
        self.assertTrue(differed)

    def test_small_shapes_pack_as_themselves(self) -> None:
        self.assertEqual([piece.name for piece in decompose(1, 1)], ["I1"])
        self.assertEqual([piece.name for piece in decompose(2, 2)], ["O"])
        self.assertEqual([piece.name for piece in decompose(1, 4)], ["I"])

    def test_stack_order_lands_lower_cells_first(self) -> None:
        pieces = stack_order(decompose(7, 53))
        index = {piece: position for position, piece in enumerate(pieces)}
        for earlier in pieces:
            for later in pieces:
                if earlier is later:
                    continue
                if lands_before(earlier, later) and not lands_before(later, earlier):
                    self.assertLess(index[earlier], index[later])


class TimelineTests(unittest.TestCase):
    def test_loop_hides_every_piece_before_restart(self) -> None:
        timeline = make_timeline(90, drop=120)
        self.assertEqual(timeline.delays[0], 0)
        self.assertGreater(timeline.total, 0)
        last = timeline.delays[-1]
        last_land = last + timeline.fall
        # The full board is visible from the last landing until the first fade.
        self.assertGreaterEqual(timeline.fade_at, last_land + 3)
        last_fade_end = last + timeline.fade_at + timeline.fade
        self.assertLess(last_fade_end, timeline.total)
        self.assertGreater(timeline.drop, 0)

    def test_svg_degrades_to_the_finished_graph(self) -> None:
        calendar = _tiny_calendar()
        pieces = pieces_for_calendar(calendar)
        svg = render_svg(calendar, pieces, "dark")
        self.assertIn("@keyframes fall", svg)
        self.assertIn("prefers-reduced-motion", svg)
        self.assertIn("animation-fill-mode:backwards", svg)
        self.assertNotIn("var(", svg)
        self.assertIn(">1 contribution in the last year<", svg)
        self.assertLess(len(svg.encode()), 1_500_000)
        # 0% and 100% of the fall are the same hidden pose, so the loop does not jump.
        block = svg.split("@keyframes fall{")[1].split("@keyframes lock")[0]
        self.assertTrue(block.startswith("0%{"))
        self.assertIn("100%{transform:translateY(", block)
        head = block[: block.index("}") + 1]
        tail = block[block.rindex("100%") : block.rindex("}") + 1]
        self.assertIn("opacity:0", head)
        self.assertIn("opacity:0", tail)
        self.assertIn("translateY(", head)
        self.assertIn("translateY(", tail)
        self.assertNotIn("<script", svg)

    def test_speed_one_matches_the_default_and_other_speeds_scale_time(self) -> None:
        calendar = _tiny_calendar()
        pieces = pieces_for_calendar(calendar)
        default = render_svg(calendar, pieces, "light")
        explicit = render_svg(calendar, pieces, "light", speed=1.0)
        fast = render_svg(calendar, pieces, "light", speed=2)
        slow = render_svg(calendar, pieces, "light", speed=0.5)
        self.assertEqual(default, explicit)
        self.assertEqual(_fall_frames(default), _fall_frames(fast))
        self.assertEqual(_fall_frames(default), _fall_frames(slow))
        self.assertEqual(_brick_refs(default), _brick_refs(fast))
        self.assertEqual(_brick_refs(default), _brick_refs(slow))
        default_duration, default_delays = _animation_clock(default)
        fast_duration, fast_delays = _animation_clock(fast)
        slow_duration, slow_delays = _animation_clock(slow)
        self.assertAlmostEqual(fast_duration * 2, default_duration, places=3)
        self.assertAlmostEqual(slow_duration, default_duration * 2, places=3)
        self.assertEqual(len(fast_delays), len(default_delays))
        self.assertEqual(len(slow_delays), len(default_delays))
        for normal_delay, fast_delay, slow_delay in zip(default_delays, fast_delays, slow_delays):
            self.assertAlmostEqual(fast_delay * 2, normal_delay, places=3)
            self.assertAlmostEqual(slow_delay, normal_delay * 2, places=3)
        self.assertNotEqual(fast_duration, default_duration)


class WindowTests(unittest.TestCase):
    def test_profile_window_is_sunday_through_saturday(self) -> None:
        start, end = profile_window(date(2026, 10, 17))
        self.assertEqual(start, date(2025, 10, 12))
        self.assertEqual(end, date(2026, 10, 17))
        self.assertEqual(start.weekday(), 6)
        self.assertEqual(end.weekday(), 5)
        self.assertEqual((end - start).days % 7, 6)

    def test_leap_day_does_not_crash(self) -> None:
        start, end = profile_window(date(2028, 2, 29))
        self.assertEqual(start.weekday(), 6)
        self.assertEqual(end.weekday(), 5)


class CalendarEdgeTests(unittest.TestCase):
    def test_empty_calendar_draws_zero_contributions(self) -> None:
        """No weeks, and a year of zeros, both draw flat empty bricks."""
        empty = calendar_from_json(
            {
                "username": "empty",
                "start": "2026-10-11",
                "end": "2026-10-17",
                "weeks": [],
            }
        )
        self.assertEqual(empty.columns, 1)
        self.assertEqual(empty.total, 0)
        self.assertEqual(len(empty.weeks[0]), 7)
        self.assertTrue(all(day.count == 0 and day.level == 0 for day in empty.weeks[0]))
        pieces = pieces_for_calendar(empty)
        self.assertEqual(coverage_errors(pieces, 7, empty.columns), [])
        svg = render_svg(empty, pieces, "light")
        self.assertIn(">0 contributions in the last year<", svg)
        body = svg.split('<g class="piece"', 1)[1]
        self.assertEqual(body.count('href="#bl0"'), 7)
        self.assertEqual(sum(body.count(f'href="#bl{level}"') for level in range(1, 5)), 0)
        self.assertNotIn("<script", svg)

        quiet = calendar_from_json(_json_calendar("quiet", date(2026, 10, 11), date(2026, 10, 24)))
        self.assertEqual(quiet.columns, 2)
        self.assertEqual(quiet.total, 0)
        self.assertGreater(sum(len(week) for week in quiet.weeks), 0)
        self.assertTrue(all(day.count == 0 and day.level == 0 for week in quiet.weeks for day in week))
        pieces = pieces_for_calendar(quiet)
        self.assertEqual(coverage_errors(pieces, 7, quiet.columns), [])
        svg = render_svg(quiet, pieces, "light")
        self.assertIn(">0 contributions in the last year<", svg)
        body = svg.split('<g class="piece"', 1)[1]
        self.assertEqual(body.count('href="#bl0"'), 14)
        self.assertNotIn("<circle", body)

    def test_leap_year_keeps_all_366_days(self) -> None:
        """Jan 1 through Dec 31 of a leap year is 366 days and includes Feb 29."""
        start = date(2024, 1, 1)
        end = date(2024, 12, 31)
        leap = date(2024, 2, 29)
        payload = _json_calendar("leap", start, end, {leap: (4, 4)})
        self.assertEqual(sum(len(week) for week in payload["weeks"]), 366)
        self.assertLess(len(payload["weeks"][0]), 7)

        calendar = calendar_from_json(payload)
        dates = [day.date for week in calendar.weeks for day in week]
        self.assertEqual(sum(day.year == 2024 for day in dates), 366)
        self.assertEqual(len(dates), len(set(dates)))
        index = dates.index(leap)
        self.assertEqual(dates[index - 1], date(2024, 2, 28))
        self.assertEqual(dates[index + 1], date(2024, 3, 1))
        self.assertEqual(index % 7, 4)
        self.assertEqual(calendar.weeks[index // 7][4].count, 4)
        self.assertEqual(calendar.total, 4)
        self.assertEqual(calendar.start.weekday(), 6)
        self.assertEqual(calendar.end.weekday(), 5)
        self.assertTrue(all(len(week) == 7 for week in calendar.weeks))

        pieces = pieces_for_calendar(calendar)
        self.assertEqual(coverage_errors(pieces, 7, calendar.columns), [])
        svg = render_svg(calendar, pieces, "dark")
        self.assertIn(">4 contributions in the last year<", svg)
        self.assertIn(calendar.start.isoformat(), svg)
        self.assertIn(calendar.end.isoformat(), svg)
        body = svg.split('<g class="piece"', 1)[1]
        self.assertEqual(body.count('href="#bd4"'), 1)
        self.assertNotIn("<script", svg)

    def test_partial_first_week_aligns_to_sunday(self) -> None:
        """A first week with fewer than 7 days still uses Sunday as row 0.

        2026-10-14 is a Wednesday and 2026-10-27 is a Tuesday, so the 14 days
        are a whole number of weeks, but the first Sunday week only holds
        Wednesday through Saturday. Packing from the first date would label
        Thursday as Monday.
        """
        start = date(2026, 10, 14)
        end = date(2026, 10, 27)
        payload = _json_calendar("partial", start, end, {start: (3, 2)})
        self.assertEqual(len(payload["weeks"][0]), 4)
        self.assertLess(len(payload["weeks"][0]), 7)

        calendar = calendar_from_json(payload)
        self.assertEqual(calendar.start, date(2026, 10, 11))
        self.assertEqual(calendar.end, date(2026, 10, 31))
        self.assertEqual(calendar.start.weekday(), 6)
        self.assertEqual(calendar.end.weekday(), 5)
        self.assertTrue(all(len(week) == 7 for week in calendar.weeks))
        self.assertEqual([day.count for day in calendar.weeks[0][:4]], [0, 0, 0, 3])
        self.assertEqual(calendar.weeks[0][3].date, start)
        self.assertEqual(calendar.weeks[0][3].level, 2)
        self.assertEqual(calendar.total, 3)

        pieces = pieces_for_calendar(calendar)
        self.assertEqual(coverage_errors(pieces, 7, calendar.columns), [])
        svg = render_svg(calendar, pieces, "light")
        self.assertIn(">3 contributions in the last year<", svg)
        self.assertIn(">Oct<", svg)
        self.assertIn(">Wed<", svg)
        body = svg.split('<g class="piece"', 1)[1]
        self.assertGreater(body.count('href="#bl2"'), 0)
        self.assertNotIn("<script", svg)

    def test_dump_json_round_trip_keeps_levels(self) -> None:
        """calendar_to_json writes integer level, and a reload keeps those colors.

        contributionLevel still wins when a day also carries an integer level,
        which is the shape a fetched GitHub day would have.
        """
        start = date(2026, 10, 11)
        end = date(2026, 10, 17)
        original = calendar_from_json(
            _json_calendar(
                "round",
                start,
                end,
                {
                    date(2026, 10, 12): (3, 2),
                    date(2026, 10, 14): (8, 4),
                },
            )
        )
        payload = calendar_to_json(original)
        monday = payload["weeks"][0][1]
        wednesday = payload["weeks"][0][3]
        self.assertEqual(monday, {"date": "2026-10-12", "count": 3, "level": 2})
        self.assertEqual(wednesday["level"], 4)
        self.assertNotIn("contributionLevel", monday)

        restored = calendar_from_json(payload)
        self.assertEqual(restored.username, original.username)
        self.assertEqual(restored.start, original.start)
        self.assertEqual(restored.end, original.end)
        self.assertEqual(restored.total, 11)
        self.assertEqual(
            [(day.date, day.count, day.level) for week in restored.weeks for day in week],
            [(day.date, day.count, day.level) for week in original.weeks for day in week],
        )
        for theme, empty, colored in (("light", "bl0", "bl"), ("dark", "bd0", "bd")):
            body = render_svg(restored, pieces_for_calendar(restored), theme).split('<g class="piece"', 1)[1]
            self.assertGreater(body.count(f'href="#{colored}2"'), 0)
            self.assertGreater(body.count(f'href="#{colored}4"'), 0)
            self.assertLess(body.count(f'href="#{empty}"'), 7)

        # The API enum wins over a stale integer level. An integer
        # contributionLevel is still a level, and a date-only day stays empty.
        mixed = calendar_from_json(
            {
                "username": "mixed",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "weeks": [
                    [
                        {
                            "date": "2026-10-12",
                            "contributionCount": 9,
                            "count": 1,
                            "contributionLevel": "FOURTH_QUARTILE",
                            "level": 1,
                        },
                        {"date": "2026-10-13", "contributionCount": 2, "contributionLevel": 3},
                        {"date": "2026-10-14"},
                    ]
                ],
            }
        )
        self.assertEqual(mixed.weeks[0][1].count, 9)
        self.assertEqual(mixed.weeks[0][1].level, 4)
        self.assertEqual(mixed.weeks[0][2].count, 2)
        self.assertEqual(mixed.weeks[0][2].level, 3)
        self.assertEqual(mixed.weeks[0][3].count, 0)
        self.assertEqual(mixed.weeks[0][3].level, 0)

    def test_unusable_calendar_json_names_the_bad_field(self) -> None:
        """Levels outside 0 to 4, and other bad days, fail while loading.

        A level of -1 used to load. The brick href pointed at a missing symbol,
        and a joint between two such days borrowed the level 4 color.
        """
        start = "2026-10-11"
        end = "2026-10-17"

        def day(**extra: object) -> dict:
            body: dict = {"date": "2026-10-12", "count": 1, "level": 1}
            body.update(extra)
            return {"username": "bad", "start": start, "end": end, "weeks": [[body]]}

        rejected = (
            (day(level=-1), ("2026-10-12", "level", "0 to 4", "FIRST_QUARTILE")),
            (day(level=5), ("2026-10-12", "level", "0 to 4")),
            (day(level=True), ("2026-10-12", "level", "True")),
            (day(contributionLevel="BOGUS"), ("contributionLevel", "BOGUS", "FOURTH_QUARTILE")),
            (day(contributionLevel="none"), ("contributionLevel", "NONE")),
            (day(count=-3), ("2026-10-12", "count", "-3")),
            (day(count=1.5), ("count", "1.5")),
            (day(count=True), ("count", "True")),
            (day(date="2026-13-40"), ("2026-13-40", "ISO date")),
            (day(date=""), ("ISO date",)),
            (day(date=None), ("date", "ISO date")),
            ({"username": "bad", "end": end, "weeks": []}, ("start", "missing")),
            ({"username": "bad", "start": start, "end": end}, ("weeks", "missing")),
            ({"username": "bad", "start": end, "end": start, "weeks": []}, ("before", "2026-10-17")),
            ([], ("JSON object",)),
            ({"start": start, "end": end, "weeks": ["nope"]}, ("week 1",)),
            ({"start": start, "end": end, "weeks": [["2026-10-12"]]}, ("object", "date")),
            (
                {"start": start, "end": end, "weeks": [[day()["weeks"][0][0]], [day(count=3)["weeks"][0][0]]]},
                ("2026-10-12", "more than once"),
            ),
        )
        for payload, needles in rejected:
            with self.assertRaises(CalendarParseError) as caught:
                calendar_from_json(payload)
            message = str(caught.exception)
            for needle in needles:
                self.assertIn(needle, message, message)

        monday = calendar_from_json(day(count="4", level="2"))
        self.assertEqual(monday.weeks[0][1].date, date(2026, 10, 12))
        self.assertEqual(monday.weeks[0][1].count, 4)
        self.assertEqual(monday.weeks[0][1].level, 2)
        self.assertEqual(monday.total, 4)

        enum_wins = calendar_from_json(
            day(level=1, contributionLevel=" FOURTH_QUARTILE ", contributionCount="8")
        )
        self.assertEqual(enum_wins.weeks[0][1].level, 4)
        self.assertEqual(enum_wins.weeks[0][1].count, 8)

        for level in (0, 4):
            bounded = calendar_from_json(day(level=level, count=level))
            self.assertEqual(bounded.weeks[0][1].level, level)
            self.assertEqual(bounded.weeks[0][1].count, level)


class SampleTests(unittest.TestCase):
    def test_nonzero_contributions_render_colored_bricks(self) -> None:
        """A calendar with activity must paint bricks other than the empty level.

        The legend uses bl1–bl4 once each, so those swatches do not count.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location("make_demo", ROOT / "scripts" / "make_demo.py")
        if spec is None or spec.loader is None:
            self.fail("scripts/make_demo.py could not be loaded")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        calendar = _tiny_calendar()
        self.assertGreater(calendar.total, 0)
        payload = module.calendar_payload(calendar)
        active = next(
            day for week in payload["weeks"] for day in week if day["contributionCount"] > 0
        )
        self.assertEqual(active["contributionLevel"], "FIRST_QUARTILE")
        self.assertNotIn("level", active)

        loaded = calendar_from_json(payload)
        self.assertGreater(sum(day.level > 0 for week in loaded.weeks for day in week), 0)
        svg = render_svg(loaded, pieces_for_calendar(loaded), "light")
        pieces = svg.split('<g class="piece"', 1)[1]
        colored = sum(pieces.count(f'href="#bl{level}"') for level in range(1, 5))
        self.assertGreater(colored, 0)

    def test_saved_calendar_matches_kenyanl_window(self) -> None:
        if not SAMPLE.exists():
            self.skipTest("sample calendar not generated yet")
        import json

        calendar = calendar_from_json(json.loads(SAMPLE.read_text(encoding="utf-8")))
        self.assertEqual(calendar.username, "KenYanL")
        self.assertEqual(calendar.columns, 53)
        self.assertEqual(calendar.total, 168)
        pieces = pieces_for_calendar(calendar)
        self.assertEqual(coverage_errors(pieces, 7, 53), [])
        for theme in ("light", "dark"):
            svg = render_svg(calendar, pieces, theme)
            self.assertIn("#aceebb" if theme == "light" else "#56d364", svg)
            self.assertIn("KenYanL", svg)
            self.assertLess(len(svg.encode()), 1_500_000)

    def test_pinned_sample_svgs_match_the_generator(self) -> None:
        """The committed sample drawings are a render of the pinned calendar.

        Those SVGs were written when an integer level was ignored, so the
        caption said 168 contributions while every cell was an empty brick.
        """
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "generate.py"),
                    "--input",
                    str(SAMPLE),
                    "--out",
                    tmp,
                    "--seed",
                    "0",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            for name in ("tetris-contrib.svg", "tetris-contrib-dark.svg"):
                rebuilt = Path(tmp) / name
                original = ROOT / "sample" / name
                self.assertTrue(original.is_file(), name)
                if rebuilt.read_bytes() != original.read_bytes():
                    self.fail(
                        f"sample/{name} does not match generate.py. "
                        "Rerun generate.py --input sample/contributions.json --out sample."
                    )
            light = (ROOT / "sample" / "tetris-contrib.svg").read_text(encoding="utf-8")
            body = light.split('<g class="piece"', 1)[1]
            colored = sum(body.count(f'href="#bl{level}"') for level in range(1, 5))
            self.assertGreater(colored, 0)
            self.assertIn(">168 contributions in the last year<", light)


class DemoTests(unittest.TestCase):
    def test_committed_demo_matches_seeded_rebuild(self) -> None:
        """The README preview stays the seeded synthetic demo, not a live calendar."""
        names = ("contributions.json", "tetris-contrib.svg", "tetris-contrib-dark.svg")
        committed = ROOT / "demo"
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "make_demo.py"), "--out", tmp],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            rebuilt_root = Path(tmp)
            for name in names:
                rebuilt = rebuilt_root / name
                original = committed / name
                self.assertTrue(rebuilt.is_file(), name)
                self.assertTrue(
                    original.is_file(),
                    f"demo/{name} is missing. Rerun scripts/make_demo.py.",
                )
                if rebuilt.read_bytes() != original.read_bytes():
                    self.fail(
                        f"demo/{name} does not match the seeded rebuild. Rerun scripts/make_demo.py."
                    )
            light = (rebuilt_root / "tetris-contrib.svg").read_text(encoding="utf-8")
            self.assertIn(">demo contributions, built from falling bricks<", light)
            self.assertNotIn("KenYanL", light)


class GenerateCliTests(unittest.TestCase):
    def test_explicit_paths_and_default_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            light = Path(tmp) / "light.svg"
            dark = Path(tmp) / "nested" / "dark.svg"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "generate.py"),
                    "--input",
                    str(SAMPLE),
                    "--light",
                    str(light),
                    "--dark",
                    str(dark),
                    "--seed",
                    "0",
                    "--print-stats",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(light.is_file())
            self.assertTrue(dark.is_file())
            self.assertIn("#aceebb", light.read_text(encoding="utf-8"))
            self.assertIn("#56d364", dark.read_text(encoding="utf-8"))
            self.assertLess(light.stat().st_size, 80_000)


class InputValidationTests(unittest.TestCase):
    def test_username_names_the_input_and_a_valid_login(self) -> None:
        with self.assertRaises(InputError) as empty:
            checked_username("", required=True)
        self.assertIn("github_user_name", str(empty.exception))
        self.assertIn("octocat", str(empty.exception))
        self.assertIsNone(checked_username("", required=False))
        self.assertIsNone(checked_username(None, required=False))
        for bad in ("-ab", "ab-", "a--b", "has space", "a" * 40, "user_name", "."):
            with self.assertRaises(InputError) as caught:
                checked_username(bad, required=True)
            message = str(caught.exception)
            self.assertIn("github_user_name", message)
            self.assertIn(bad, message)
            self.assertIn("octocat", message)
        self.assertEqual(checked_username("KenYanL", required=True), "KenYanL")
        self.assertEqual(checked_username("a", required=True), "a")
        self.assertEqual(checked_username("a-b", required=True), "a-b")

    def test_seed_rejects_non_integers_and_out_of_range_values(self) -> None:
        self.assertEqual(parse_seed("0"), 0)
        self.assertEqual(parse_seed(0), 0)
        self.assertEqual(parse_seed("+1"), 1)
        self.assertEqual(parse_seed("-1"), -1)
        self.assertEqual(parse_seed(str(2_147_483_647)), 2_147_483_647)
        self.assertEqual(parse_seed(str(-2_147_483_648)), -2_147_483_648)
        for bad in ("nope", "1.5", "", "2147483648", "-2147483649", True):
            with self.assertRaises(InputError) as caught:
                parse_seed(bad)
            message = str(caught.exception)
            self.assertIn("seed", message)
            self.assertIn("-2147483648", message)
            self.assertIn("2147483647", message)

    def test_speed_rejects_non_numeric_and_non_positive(self) -> None:
        self.assertEqual(parse_speed("1"), 1.0)
        self.assertEqual(parse_speed("1.0"), 1.0)
        self.assertEqual(parse_speed(1), 1.0)
        self.assertEqual(parse_speed(1.0), 1.0)
        self.assertEqual(parse_speed("2"), 2.0)
        self.assertEqual(parse_speed("+0.5"), 0.5)
        self.assertEqual(parse_speed(" 2.5 "), 2.5)
        for bad in ("nope", "", "   ", "0", "0.0", "-1", "-0.5", "inf", "nan", "1.2.3", True, None):
            with self.assertRaises(InputError) as caught:
                parse_speed(bad)
            message = str(caught.exception)
            self.assertIn("speed", message)
            self.assertIn("positive", message)
            self.assertIn("0.5", message)

    def test_output_paths_name_the_input_and_an_example(self) -> None:
        light = validate_output_path(
            "dist/tetris-contrib.svg",
            "svg_light_path (--light)",
            example="dist/tetris-contrib.svg",
            relative=True,
        )
        self.assertEqual(light.as_posix(), "dist/tetris-contrib.svg")
        absolute = validate_output_path(
            "/tmp/light.svg",
            "svg_light_path (--light)",
            example="dist/tetris-contrib.svg",
            relative=False,
        )
        self.assertTrue(absolute.is_absolute())
        for bad in ("", "   ", "dist/", "../x.svg", "dist/../x.svg", "file.png", "/tmp/a.svg", "a.svg\n"):
            with self.assertRaises(InputError) as caught:
                validate_output_path(
                    bad,
                    "svg_light_path (--light)",
                    example="dist/tetris-contrib.svg",
                    relative=True,
                )
            message = str(caught.exception)
            self.assertIn("svg_light_path", message)
            self.assertIn("dist/tetris-contrib.svg", message)

    def test_input_paths_name_the_input_and_an_example(self) -> None:
        calendar = validate_input_path(
            "sample/contributions.json",
            "calendar_json (--input)",
            example="sample/contributions.json",
            relative=True,
        )
        self.assertEqual(calendar.as_posix(), "sample/contributions.json")
        absolute = validate_input_path(
            "/tmp/a.json",
            "calendar_json (--input)",
            example="sample/contributions.json",
            relative=False,
        )
        self.assertTrue(absolute.is_absolute())
        for bad in (
            "",
            "   ",
            "sample/",
            "../x.json",
            "sample/../x.json",
            "file.txt",
            "/tmp/a.json",
            "a.json\n",
        ):
            with self.assertRaises(InputError) as caught:
                validate_input_path(
                    bad,
                    "calendar_json (--input)",
                    example="sample/contributions.json",
                    relative=True,
                )
            message = str(caught.exception)
            self.assertIn("calendar_json", message)
            self.assertIn("sample/contributions.json", message)

    def test_cli_rejects_bad_inputs_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            light = Path(tmp) / "light.svg"
            dark = Path(tmp) / "nested" / "dark.svg"
            env = os.environ.copy()
            env.pop("GITHUB_TOKEN", None)
            env.pop("GITHUB_ACTOR", None)
            env.pop("GITHUB_USERNAME", None)
            env.pop("TETRIS_REQUIRE_RELATIVE", None)

            empty_user = _run_generate(
                ["--username", "", "--token", "dummy", "--light", str(light), "--dark", str(dark)],
                env=env,
            )
            self.assertNotEqual(empty_user.returncode, 0)
            self.assertIn("github_user_name", empty_user.stderr)
            self.assertIn("octocat", empty_user.stderr)
            self.assertNotIn("GraphQL", empty_user.stderr)
            self.assertFalse(light.exists())

            bad_name = _run_generate(
                [
                    "--input",
                    str(SAMPLE),
                    "--username",
                    "bad--name",
                    "--light",
                    str(light),
                    "--dark",
                    str(dark),
                ],
                env=env,
            )
            self.assertNotEqual(bad_name.returncode, 0)
            self.assertIn("github_user_name", bad_name.stderr)
            self.assertIn("bad--name", bad_name.stderr)
            self.assertFalse(light.exists())

            bad_seed = _run_generate(
                ["--input", str(SAMPLE), "--light", str(light), "--dark", str(dark), "--seed", "nope"],
                env=env,
            )
            self.assertNotEqual(bad_seed.returncode, 0)
            self.assertIn("seed", bad_seed.stderr)
            self.assertIn("-2147483648", bad_seed.stderr)
            self.assertFalse(light.exists())

            bad_path = _run_generate(
                ["--input", str(SAMPLE), "--light", "../out.svg", "--dark", str(dark), "--seed", "0"],
                env=env,
            )
            self.assertNotEqual(bad_path.returncode, 0)
            self.assertIn("svg_light_path", bad_path.stderr)
            self.assertIn("dist/tetris-contrib.svg", bad_path.stderr)
            self.assertFalse(light.exists())
            self.assertFalse(dark.exists())

            same = _run_generate(
                ["--input", str(SAMPLE), "--light", "dist/same.svg", "--dark", "dist/./same.svg", "--seed", "0"],
                env=env,
            )
            self.assertNotEqual(same.returncode, 0)
            self.assertIn("svg_light_path", same.stderr)
            self.assertIn("svg_dark_path", same.stderr)

            blank_token = _run_generate(
                ["--username", "octocat", "--token", "  ", "--light", str(light), "--dark", str(dark)],
                env=env,
            )
            self.assertNotEqual(blank_token.returncode, 0)
            self.assertIn("token", blank_token.stderr)
            self.assertIn("GITHUB_TOKEN", blank_token.stderr)
            self.assertNotIn("GraphQL", blank_token.stderr)
            self.assertFalse(light.exists())

    def test_cli_rejects_bad_input_paths_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            light = Path(tmp) / "light.svg"
            dark = Path(tmp) / "dark.svg"
            env = os.environ.copy()
            env.pop("GITHUB_TOKEN", None)
            env.pop("GITHUB_ACTOR", None)
            env.pop("GITHUB_USERNAME", None)
            env.pop("TETRIS_REQUIRE_RELATIVE", None)

            for bad in ("", "   ", "../x.json", "sample/../x.json", "file.txt", "calendar.json/"):
                proc = _run_generate(
                    ["--input", bad, "--light", str(light), "--dark", str(dark), "--seed", "0"],
                    env=env,
                )
                self.assertNotEqual(proc.returncode, 0, bad)
                self.assertIn("calendar_json", proc.stderr)
                self.assertIn("sample/contributions.json", proc.stderr)
                self.assertFalse(light.exists())
                self.assertFalse(dark.exists())

    def test_action_wires_calendar_json_and_workflow_publishes_demo(self) -> None:
        """The action can render a saved calendar JSON; this repo publishes demo/.

        Standing rule: never show a live contribution graph from this workflow.
        ``calendar_json`` skips the API; the publish job must use the seeded
        ``demo/contributions.json`` with username ``demo``, not KenYanL live.
        """
        action = (ROOT / "action.yml").read_text(encoding="utf-8")
        self.assertIn("\n  calendar_json:\n", action)
        self.assertIn("TETRIS_INPUT: ${{ inputs.calendar_json }}", action)
        self.assertIn('--input "$input"', action)
        self.assertIn('if [ -n "$input" ]; then', action)
        # Live-fetch path still requires a token; the calendar_json path must not.
        token_guard = (
            'echo "contrib-tetris: token is empty. Pass a non-empty GitHub token'
        )
        self.assertIn(token_guard, action)
        input_branch = action.split('if [ -n "$input" ]; then', 1)[1]
        else_branch = input_branch.split("else", 1)[1]
        self.assertIn('gen+=(--input "$input")', input_branch.split("else", 1)[0])
        self.assertIn(token_guard, else_branch)
        self.assertIn('gen+=(--token "$token")', else_branch)
        self.assertNotIn(token_guard, input_branch.split("else", 1)[0])

        workflow = (ROOT / ".github" / "workflows" / "tetris.yml").read_text(encoding="utf-8")
        self.assertIn("calendar_json: demo/contributions.json", workflow)
        self.assertIn("github_user_name: demo", workflow)
        self.assertNotIn("github_user_name: KenYanL", workflow)
        self.assertIn("seeded", workflow.lower())
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("`calendar_json`", readme)
        self.assertIn("demo/contributions.json", readme)
        self.assertIn("does not fetch", readme.lower())

    def test_action_style_inputs_still_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["TETRIS_REQUIRE_RELATIVE"] = "1"
            workspace = Path(tmp)
            relative_input = workspace / "sample" / "contributions.json"
            relative_input.parent.mkdir(parents=True)
            relative_input.write_bytes(SAMPLE.read_bytes())
            proc = _run_generate(
                [
                    "--input",
                    "sample/contributions.json",
                    "--username",
                    "KenYanL",
                    "--light",
                    "dist/tetris-contrib.svg",
                    "--dark",
                    "dist/tetris-contrib-dark.svg",
                    "--seed",
                    "0",
                ],
                env=env,
                cwd=tmp,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            light = workspace / "dist" / "tetris-contrib.svg"
            dark = workspace / "dist" / "tetris-contrib-dark.svg"
            self.assertIn("#aceebb", light.read_text(encoding="utf-8"))
            self.assertIn("#56d364", dark.read_text(encoding="utf-8"))
            self.assertIn("KenYanL", light.read_text(encoding="utf-8"))

            absolute = _run_generate(
                [
                    "--input",
                    "sample/contributions.json",
                    "--light",
                    str(workspace / "abs.svg"),
                    "--dark",
                    "dist/tetris-contrib-dark.svg",
                    "--seed",
                    "1",
                ],
                env=env,
                cwd=tmp,
            )
            self.assertNotEqual(absolute.returncode, 0)
            self.assertIn("svg_light_path", absolute.stderr)
            self.assertIn("relative", absolute.stderr)
            self.assertFalse((workspace / "abs.svg").exists())

            absolute_input = _run_generate(
                [
                    "--input",
                    str(SAMPLE),
                    "--light",
                    "other/tetris-contrib.svg",
                    "--dark",
                    "other/tetris-contrib-dark.svg",
                    "--seed",
                    "0",
                ],
                env=env,
                cwd=tmp,
            )
            self.assertNotEqual(absolute_input.returncode, 0)
            self.assertIn("calendar_json", absolute_input.stderr)
            self.assertIn("relative", absolute_input.stderr)
            self.assertIn("sample/contributions.json", absolute_input.stderr)
            self.assertFalse((workspace / "other" / "tetris-contrib.svg").exists())
            self.assertFalse((workspace / "other" / "tetris-contrib-dark.svg").exists())

    def test_cli_rejects_outputs_that_cannot_be_written(self) -> None:
        """A path that cannot be written fails before any SVG or JSON is created.

        ``--out`` used to raise FileExistsError when it named a file, and
        ``--dump-json`` used to raise IsADirectoryError or be overwritten by
        the light SVG. An existing SVG inside a real directory is replaced.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = os.environ.copy()
            blocker = root / "not-a-dir"
            blocker.write_text("keep", encoding="utf-8")

            def rejected(args: list[str], *needles: str) -> None:
                proc = _run_generate(args, env=env)
                self.assertEqual(proc.returncode, 1, proc.stderr)
                self.assertIn("contrib-tetris:", proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)
                for needle in needles:
                    self.assertIn(needle, proc.stderr)

            rejected(
                ["--input", str(SAMPLE), "--out", str(blocker)],
                "--out",
                str(blocker),
                "not a directory",
                "dist",
            )
            self.assertEqual(blocker.read_text(encoding="utf-8"), "keep")

            rejected(
                ["--input", str(SAMPLE), "--out", str(blocker / "sub")],
                "--out",
                str(blocker),
                "is a file",
                "dist",
            )
            self.assertFalse((blocker / "sub").exists())

            calendar_dir = root / "calendar-dir"
            calendar_dir.mkdir()
            svg_out = root / "svg-out"
            rejected(
                ["--input", str(SAMPLE), "--out", str(svg_out), "--dump-json", str(calendar_dir)],
                "--dump-json",
                str(calendar_dir),
                "is a directory",
                "dist/contributions.json",
            )
            self.assertFalse(svg_out.exists())

            same = root / "same-out"
            rejected(
                ["--input", str(SAMPLE), "--out", str(same), "--dump-json", str(same)],
                "--dump-json",
                str(same),
                "same path as --out",
                "dist/contributions.json",
            )
            self.assertFalse(same.exists())

            clash = root / "clash"
            rejected(
                [
                    "--input",
                    str(SAMPLE),
                    "--out",
                    str(clash),
                    "--dump-json",
                    str(clash / "tetris-contrib.svg"),
                ],
                "--dump-json",
                "same file as the light SVG",
                "dist/contributions.json",
            )
            self.assertFalse(clash.exists())

            light_dir = root / "light.svg"
            light_dir.mkdir()
            dark = root / "dark.svg"
            rejected(
                ["--input", str(SAMPLE), "--light", str(light_dir), "--dark", str(dark)],
                "svg_light_path",
                str(light_dir),
                "is a directory",
                "dist/tetris-contrib.svg",
            )
            self.assertFalse(dark.exists())

            rejected(
                ["--input", str(SAMPLE), "--light", str(blocker / "light.svg"), "--dark", str(dark)],
                "svg_light_path",
                str(blocker),
                "is a file",
                "dist/tetris-contrib.svg",
            )
            self.assertFalse(dark.exists())
            self.assertEqual(blocker.read_text(encoding="utf-8"), "keep")

            nested_dump = blocker / "calendar.json"
            ok_out = root / "ok-out"
            rejected(
                ["--input", str(SAMPLE), "--out", str(ok_out), "--dump-json", str(nested_dump)],
                "--dump-json",
                str(blocker),
                "is a file",
                "dist/contributions.json",
            )
            self.assertFalse(ok_out.exists())
            self.assertFalse(nested_dump.exists())

            ready = root / "ready"
            ready.mkdir()
            (ready / "tetris-contrib.svg").write_text("old", encoding="utf-8")
            (ready / "tetris-contrib-dark.svg").write_text("old", encoding="utf-8")
            replaced = _run_generate(
                [
                    "--input",
                    str(SAMPLE),
                    "--out",
                    str(ready),
                    "--dump-json",
                    str(ready / "calendar.json"),
                ],
                env=env,
            )
            self.assertEqual(replaced.returncode, 0, replaced.stderr)
            self.assertTrue((ready / "tetris-contrib.svg").read_text(encoding="utf-8").startswith("<?xml"))
            self.assertTrue((ready / "tetris-contrib-dark.svg").read_text(encoding="utf-8").startswith("<?xml"))
            saved = (ready / "calendar.json").read_text(encoding="utf-8")
            self.assertIn('"level"', saved)
            self.assertNotIn("<?xml", saved)

    def test_cli_rejects_bad_speed_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            light = Path(tmp) / "light.svg"
            dark = Path(tmp) / "dark.svg"
            missing = Path(tmp) / "missing.json"
            env = os.environ.copy()
            for bad in ("nope", "0", "-1", ""):
                proc = _run_generate(
                    [
                        "--input",
                        str(missing),
                        "--light",
                        str(light),
                        "--dark",
                        str(dark),
                        "--speed",
                        bad,
                    ],
                    env=env,
                )
                self.assertNotEqual(proc.returncode, 0, bad)
                self.assertIn("speed", proc.stderr)
                self.assertIn("positive", proc.stderr)
                self.assertIn("0.5", proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)
                self.assertFalse(light.exists())
                self.assertFalse(dark.exists())
                self.assertFalse(missing.exists())

    def test_cli_default_speed_matches_one_and_faster_speed_scales(self) -> None:
        import json

        payload = _json_calendar(
            "demo",
            date(2026, 10, 11),
            date(2026, 10, 17),
            {date(2026, 10, 12): (3, 2)},
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "calendar.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            env = os.environ.copy()
            written: dict[str, tuple[str, str]] = {}
            for name, extra in (
                ("normal", []),
                ("explicit", ["--speed", "1.0"]),
                ("fast", ["--speed", "2"]),
            ):
                folder = Path(tmp) / name
                proc = _run_generate(
                    ["--input", str(source), "--out", str(folder), *extra],
                    env=env,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                written[name] = (
                    (folder / "tetris-contrib.svg").read_text(encoding="utf-8"),
                    (folder / "tetris-contrib-dark.svg").read_text(encoding="utf-8"),
                )
            self.assertEqual(written["normal"], written["explicit"])
            normal_light, normal_dark = written["normal"]
            fast_light, fast_dark = written["fast"]
            normal_duration, _delays = _animation_clock(normal_light)
            fast_duration, _fast_delays = _animation_clock(fast_light)
            self.assertAlmostEqual(fast_duration * 2, normal_duration, places=3)
            self.assertEqual(_fall_frames(normal_light), _fall_frames(fast_light))
            self.assertEqual(_fall_frames(normal_dark), _fall_frames(fast_dark))
            self.assertNotEqual(normal_light, fast_light)

    def test_cli_dump_json_reloads_with_the_same_bricks(self) -> None:
        """A --dump-json file passed back to --input keeps the colored bricks."""
        import json

        payload = _json_calendar(
            "demo",
            date(2026, 10, 11),
            date(2026, 10, 17),
            {date(2026, 10, 12): (3, 2), date(2026, 10, 14): (8, 4)},
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "calendar.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            dumped = Path(tmp) / "nested" / "calendar.json"
            first = Path(tmp) / "first"
            second = Path(tmp) / "second"
            env = os.environ.copy()
            proc = _run_generate(
                ["--input", str(source), "--out", str(first), "--dump-json", str(dumped), "--seed", "0"],
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(dumped.is_file())
            saved = json.loads(dumped.read_text(encoding="utf-8"))
            active = [day for week in saved["weeks"] for day in week if day["count"] > 0]
            self.assertEqual([day["level"] for day in active], [2, 4])
            self.assertNotIn("contributionLevel", active[0])

            again = _run_generate(
                ["--input", str(dumped), "--out", str(second), "--seed", "0"],
                env=env,
            )
            self.assertEqual(again.returncode, 0, again.stderr)
            for name in ("tetris-contrib.svg", "tetris-contrib-dark.svg"):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
            light = (second / "tetris-contrib.svg").read_text(encoding="utf-8")
            dark = (second / "tetris-contrib-dark.svg").read_text(encoding="utf-8")
            self.assertIn('href="#bl2"', light)
            self.assertIn('href="#bl4"', light)
            self.assertIn('href="#bd2"', dark)
            self.assertIn('href="#bd4"', dark)
            self.assertNotIn("#aceebb", dark)
            self.assertNotIn("#56d364", light)

    def test_cli_rejects_unusable_calendar_before_writing(self) -> None:
        """A bad --input file exits before dump or SVG output, with no traceback.

        Level -1 used to exit 0 and write an SVG whose brick href was missing.
        """
        import json

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = os.environ.copy()
            out = root / "dist"
            dumped = root / "nested" / "calendar.json"
            missing = root / "missing.json"
            missing_run = _run_generate(
                ["--input", str(missing), "--out", str(out), "--dump-json", str(dumped)],
                env=env,
            )
            self.assertEqual(missing_run.returncode, 1)
            self.assertIn("contrib-tetris:", missing_run.stderr)
            self.assertIn("--input", missing_run.stderr)
            self.assertIn(str(missing), missing_run.stderr)
            self.assertIn("was not found", missing_run.stderr)
            self.assertIn("sample/contributions.json", missing_run.stderr)
            self.assertNotIn("Traceback", missing_run.stderr)
            self.assertFalse(out.exists())
            self.assertFalse(dumped.exists())

            calendar_dir = root / "calendar.json"
            calendar_dir.mkdir()
            directory_run = _run_generate(
                ["--input", str(calendar_dir), "--out", str(out)],
                env=env,
            )
            self.assertEqual(directory_run.returncode, 1)
            self.assertIn("is a directory", directory_run.stderr)
            self.assertIn("sample/contributions.json", directory_run.stderr)
            self.assertNotIn("Traceback", directory_run.stderr)
            self.assertFalse(out.exists())

            parent_file = root / "parent-file"
            parent_file.write_text("x", encoding="utf-8")
            nested_run = _run_generate(
                ["--input", str(parent_file / "calendar.json"), "--out", str(out)],
                env=env,
            )
            self.assertEqual(nested_run.returncode, 1)
            self.assertIn("has a parent that is a file", nested_run.stderr)
            self.assertIn("sample/contributions.json", nested_run.stderr)
            self.assertNotIn("Traceback", nested_run.stderr)
            self.assertFalse(out.exists())

            if hasattr(os, "geteuid") and os.geteuid() != 0:
                locked = root / "locked.json"
                locked.write_text("{}", encoding="utf-8")
                locked.chmod(0)
                try:
                    locked_run = _run_generate(
                        ["--input", str(locked), "--out", str(out)],
                        env=env,
                    )
                finally:
                    locked.chmod(0o600)
                self.assertEqual(locked_run.returncode, 1)
                self.assertIn("permission denied", locked_run.stderr)
                self.assertNotIn("Traceback", locked_run.stderr)
                self.assertFalse(out.exists())

            binary = root / "binary.json"
            binary.write_bytes(b"\xff")
            binary_run = _run_generate(
                ["--input", str(binary), "--out", str(out)],
                env=env,
            )
            self.assertEqual(binary_run.returncode, 1)
            self.assertIn("not UTF-8", binary_run.stderr)
            self.assertNotIn("Traceback", binary_run.stderr)
            self.assertFalse(out.exists())

            broken = root / "broken.json"
            broken.write_text("{", encoding="utf-8")
            broken_run = _run_generate(
                ["--input", str(broken), "--out", str(out), "--dump-json", str(dumped)],
                env=env,
            )
            self.assertEqual(broken_run.returncode, 1)
            self.assertIn("not valid JSON", broken_run.stderr)
            self.assertIn("line 1", broken_run.stderr)
            self.assertIn("sample/contributions.json", broken_run.stderr)
            self.assertNotIn("Traceback", broken_run.stderr)
            self.assertFalse(out.exists())
            self.assertFalse(dumped.exists())

            source = root / "level.json"
            source.write_text(
                json.dumps(
                    {
                        "username": "bad",
                        "start": "2026-10-11",
                        "end": "2026-10-17",
                        "weeks": [[{"date": "2026-10-12", "count": 3, "level": -1}]],
                    }
                ),
                encoding="utf-8",
            )
            level_run = _run_generate(
                ["--input", str(source), "--out", str(out), "--dump-json", str(dumped), "--seed", "0"],
                env=env,
            )
            self.assertEqual(level_run.returncode, 1)
            self.assertIn("--input", level_run.stderr)
            self.assertIn(str(source), level_run.stderr)
            self.assertIn("2026-10-12", level_run.stderr)
            self.assertIn("0 to 4", level_run.stderr)
            self.assertIn("FIRST_QUARTILE", level_run.stderr)
            self.assertIn("sample/contributions.json", level_run.stderr)
            self.assertNotIn("Traceback", level_run.stderr)
            self.assertFalse(out.exists())
            self.assertFalse(dumped.exists())
            self.assertFalse((out / "tetris-contrib.svg").exists())


class ApiFailureTests(unittest.TestCase):
    def test_profile_window_is_always_longer_than_one_year(self) -> None:
        """Sunday of last year through Saturday of this week never fits in one year.

        A year shifts the weekday forward by one, or by two when it crosses
        29 February, so the paddings cannot both be zero.
        """
        day = date(2024, 1, 1)
        last = date(2028, 12, 31)
        while day <= last:
            start, end = profile_window(day)
            self.assertGreater((end - start).days, 365, day.isoformat())
            self.assertTrue(range_exceeds_one_year(start, end), day.isoformat())
            day += timedelta(days=1)
        # ``to`` is 23:59:59Z, so the anniversary date itself is already past.
        self.assertFalse(range_exceeds_one_year(date(2026, 1, 1), date(2026, 12, 31)))
        self.assertTrue(range_exceeds_one_year(date(2026, 1, 1), date(2027, 1, 1)))
        self.assertTrue(range_exceeds_one_year(date(2024, 2, 29), date(2025, 2, 28)))
        self.assertFalse(range_exceeds_one_year(date(2024, 2, 29), date(2025, 2, 27)))

    def test_profile_fetch_asks_for_the_default_collection(self) -> None:
        """The over-long profile window must not send from/to, and must not retry."""
        payload = _api_calendar("2026-10-12", 2, "SECOND_QUARTILE")
        with patch("brickfall._graphql", return_value=payload) as graphql:
            calendar = fetch_calendar("octocat", "token", today=date(2026, 10, 17))
        self.assertEqual(graphql.call_count, 1)
        token, query, variables = graphql.call_args.args
        self.assertEqual(token, "token")
        self.assertEqual(query, QUERY_DEFAULT)
        self.assertEqual(variables, {"login": "octocat"})
        self.assertNotIn("$from", query)
        self.assertEqual(calendar.username, "octocat")
        self.assertEqual(calendar.total, 2)

    def test_short_window_sends_from_and_to(self) -> None:
        start, end = date(2026, 10, 11), date(2026, 10, 17)
        self.assertFalse(range_exceeds_one_year(start, end))
        payload = _api_calendar("2026-10-12", 1, "FIRST_QUARTILE")
        with patch("brickfall.profile_window", return_value=(start, end)):
            with patch("brickfall._graphql", return_value=payload) as graphql:
                calendar = fetch_calendar("octocat", "token", today=date(2026, 10, 17))
        self.assertEqual(graphql.call_count, 1)
        _token, query, variables = graphql.call_args.args
        self.assertEqual(query, QUERY)
        self.assertEqual(
            variables,
            {
                "login": "octocat",
                "from": "2026-10-11T00:00:00Z",
                "to": "2026-10-17T23:59:59Z",
            },
        )
        self.assertEqual(calendar.total, 1)

    def test_year_span_error_retries_the_default_collection(self) -> None:
        """GitHub's real rejection still falls back when a shorter range is refused."""
        start, end = date(2026, 10, 11), date(2026, 10, 17)
        payload = _api_calendar("2026-10-12", 4, "FOURTH_QUARTILE")
        calls: list[tuple[str, dict]] = []

        def fake(_token: str, query: str, variables: dict) -> dict:
            calls.append((query, variables))
            if query == QUERY:
                raise GraphQLError(
                    "The total time spanned by 'from' and 'to' must not exceed 1 year"
                )
            return payload

        with patch("brickfall.profile_window", return_value=(start, end)):
            with patch("brickfall._graphql", side_effect=fake):
                calendar = fetch_calendar("octocat", "token", today=date(2026, 10, 17))
        self.assertEqual(
            calls,
            [
                (
                    QUERY,
                    {
                        "login": "octocat",
                        "from": "2026-10-11T00:00:00Z",
                        "to": "2026-10-17T23:59:59Z",
                    },
                ),
                (QUERY_DEFAULT, {"login": "octocat"}),
            ],
        )
        self.assertEqual(calendar.total, 4)

    def test_other_graphql_errors_are_not_retried(self) -> None:
        start, end = date(2026, 10, 11), date(2026, 10, 17)
        with patch("brickfall.profile_window", return_value=(start, end)):
            with patch(
                "brickfall._graphql",
                side_effect=GraphQLError("bad credentials"),
            ) as graphql:
                with self.assertRaises(GraphQLError) as caught:
                    fetch_calendar("octocat", "token", today=date(2026, 10, 17))
        self.assertEqual(str(caught.exception), "bad credentials")
        self.assertEqual(graphql.call_count, 1)

    def test_fetch_names_a_missing_user_and_an_empty_calendar(self) -> None:
        """These are the messages the README says the action fails with."""
        with patch("brickfall._graphql", return_value={"user": None}):
            with self.assertRaises(GraphQLError) as missing:
                fetch_calendar("octocat", "token", today=date(2026, 10, 17))
        self.assertEqual(str(missing.exception), "GitHub user 'octocat' was not found")

        empty = {
            "user": {
                "contributionsCollection": {
                    "contributionCalendar": {"weeks": []},
                }
            }
        }
        with patch("brickfall._graphql", return_value=empty):
            with self.assertRaises(GraphQLError) as quiet:
                fetch_calendar("octocat", "token", today=date(2026, 10, 17))
        self.assertEqual(str(quiet.exception), "no contribution days returned for octocat")

    def test_http_and_network_errors_are_graphql_errors(self) -> None:
        http_error = urllib.error.HTTPError(
            url="https://api.github.com/graphql",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b"bad credentials"),
        )
        with patch("urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(GraphQLError) as http:
                _graphql("token", "query { viewer { login } }", {})
        self.assertIn("HTTP 401", str(http.exception))
        self.assertIn("bad credentials", str(http.exception))

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")):
            with self.assertRaises(GraphQLError) as network:
                _graphql("token", "query { viewer { login } }", {})
        self.assertIn("timed out", str(network.exception))

    def test_cli_prints_graphql_errors_and_writes_nothing(self) -> None:
        """API failures used to escape as a traceback after inputs were accepted."""
        messages = (
            "GitHub user 'octocat' was not found",
            "no contribution days returned for octocat",
            "GitHub GraphQL HTTP 401: bad credentials",
        )
        with tempfile.TemporaryDirectory() as tmp:
            light = Path(tmp) / "nested" / "light.svg"
            dark = Path(tmp) / "nested" / "dark.svg"
            for message in messages:
                stderr = io.StringIO()
                with patch("generate.fetch_calendar", side_effect=GraphQLError(message)):
                    with contextlib.redirect_stderr(stderr):
                        code = generate.main(
                            [
                                "--username",
                                "octocat",
                                "--token",
                                "dummy",
                                "--light",
                                str(light),
                                "--dark",
                                str(dark),
                            ]
                        )
                self.assertEqual(code, 1, message)
                output = stderr.getvalue()
                self.assertIn("contrib-tetris:", output)
                self.assertIn(message, output)
                self.assertNotIn("Traceback", output)
                self.assertFalse(light.exists(), message)
                self.assertFalse(dark.exists(), message)
                self.assertFalse(light.parent.exists(), message)


def _channel(value: int) -> float:
    scaled = value / 255
    if scaled <= 0.04045:
        return scaled / 12.92
    return ((scaled + 0.055) / 1.055) ** 2.4


def _contrast(left: str, right: str) -> float:
    """WCAG contrast ratio of two #rrggbb colors."""

    def luminance(color: str) -> float:
        red, green, blue = (int(color[index : index + 2], 16) for index in (1, 3, 5))
        return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)

    lighter = max(luminance(left), luminance(right))
    darker = min(luminance(left), luminance(right))
    return (lighter + 0.05) / (darker + 0.05)


def _lunar_window() -> tuple[date, ...]:
    """Festival day plus the following days, using the catalog's span."""
    return tuple(
        anchor + timedelta(days=offset)
        for anchor in LUNAR_NEW_YEAR_DATES
        for offset in range(LUNAR_NEW_YEAR_SPAN_DAYS)
    )


def _auto_choice(day: date):
    """The palette or fade ``auto`` should select on ``day``."""
    if day in AUTO_TRANSITIONS_DATES:
        return AUTO_TRANSITIONS_DATES[day]
    key = (day.month, day.day)
    if key in AUTO_TRANSITIONS_DAYS:
        return AUTO_TRANSITIONS_DAYS[key]
    dated = {when: name for name, spec in PALETTE_CATALOG for when in spec.auto_dates}
    recurring = {(month, day_): name for name, spec in PALETTE_CATALOG for month, day_ in spec.auto_days}
    return dated.get(day, recurring.get(key, "default"))


class PaletteTests(unittest.TestCase):
    """Holiday colors, and the UTC date switch for palette auto.

    The date is passed in. These tests do not read the clock.
    """

    def test_parse_palette_names(self) -> None:
        lunar_days = (
            "17-19 February 2026, 6-8 February 2027, 26-28 January 2028, "
            "13-15 February 2029, 3-5 February 2030, 23-25 January 2031, "
            "11-13 February 2032, 31 January-2 February 2033, "
            "19-21 February 2034, and 8-10 February 2035"
        )
        fade_help = (
            " When a Chinese traditional festival and a Western holiday share a UTC day, "
            "auto starts on the Chinese palette and fades into the Western palette. "
            "A value such as lunarnewyear>valentine paints that fade on any day."
        )
        hint = (
            "Use default for the usual green graph, halloween for GitHub's Halloween "
            "colors, christmas for Coolors' popular Christmas palette, newyear for "
            "Color Hunt's New Year gold palette, valentine for SchemeColor's "
            "Valentine's Hearts palette, lunarnewyear for SchemeColor's "
            "Chinese gold and red palette, or auto to use halloween "
            "on 31 October (UTC), christmas on 24-26 December (UTC), newyear on "
            "1 January (UTC), valentine on 14 February (UTC), lunarnewyear on "
            + lunar_days
            + " (UTC), and default every other day."
            + fade_help
        )
        self.assertEqual(palette_hint(), hint)
        self.assertEqual(format_auto_dates(_lunar_window()), lunar_days)
        self.assertEqual(parse_palette("default"), "default")
        self.assertEqual(parse_palette(" Halloween "), "halloween")
        self.assertEqual(parse_palette(" Christmas "), "christmas")
        self.assertEqual(parse_palette(" NewYear "), "newyear")
        self.assertEqual(parse_palette(" Valentine "), "valentine")
        self.assertEqual(parse_palette(" LunarNewYear "), "lunarnewyear")
        self.assertEqual(parse_palette(" LunarNewYear > Valentine "), "lunarnewyear>valentine")
        self.assertEqual(parse_palette("AUTO"), "auto")
        for bad in ("", " ", "green", "seasonal", "winter", "none", "0", None, 1, True):
            with self.assertRaises(InputError) as caught:
                parse_palette(bad)
            message = str(caught.exception)
            self.assertIn("palette", message)
            self.assertIn("halloween", message)
            self.assertIn("christmas", message)
            self.assertIn("newyear", message)
            self.assertIn("valentine", message)
            self.assertIn("lunarnewyear", message)
            self.assertIn("31 October", message)
            self.assertIn("24-26 December", message)
            self.assertIn("1 January", message)
            self.assertIn("14 February", message)
            self.assertIn("17-19 February 2026", message)
            self.assertIn("lunarnewyear>valentine", message)

    def test_auto_palette_is_halloween_only_on_october_31(self) -> None:
        for year in (2020, 2024, 2026, 2028):
            self.assertEqual(resolve_palette("auto", date(year, 10, 31)), "halloween")
            self.assertEqual(resolve_palette("auto", date(year, 10, 30)), "default")
            self.assertEqual(resolve_palette("auto", date(year, 11, 1)), "default")
        self.assertEqual(resolve_palette("halloween", date(2026, 11, 1)), "halloween")
        self.assertEqual(resolve_palette("halloween", date(2026, 12, 25)), "halloween")
        self.assertEqual(resolve_palette("default", date(2026, 10, 31)), "default")
        with self.assertRaises(ValueError):
            resolve_palette("green", date(2026, 10, 31))

    def test_auto_palette_is_christmas_on_december_24_through_26(self) -> None:
        for year in (2020, 2024, 2026, 2028):
            for day in (24, 25, 26):
                self.assertEqual(resolve_palette("auto", date(year, 12, day)), "christmas")
            self.assertEqual(resolve_palette("auto", date(year, 12, 23)), "default")
            self.assertEqual(resolve_palette("auto", date(year, 12, 27)), "default")
            self.assertEqual(resolve_palette("auto", date(year, 10, 31)), "halloween")
        self.assertEqual(resolve_palette("christmas", date(2026, 12, 23)), "christmas")
        self.assertEqual(resolve_palette("christmas", date(2026, 11, 1)), "christmas")
        self.assertEqual(resolve_palette("default", date(2026, 12, 25)), "default")

    def test_auto_palette_is_newyear_only_on_january_1(self) -> None:
        """1 January is newyear. 31 December and 2 January stay the green graph.

        Christmas stays 24-26 December. Forcing ``newyear`` does not follow the date.
        """
        for year in (2020, 2024, 2026, 2028):
            self.assertEqual(resolve_palette("auto", date(year, 1, 1)), "newyear")
            self.assertEqual(resolve_palette("auto", date(year, 1, 2)), "default")
            self.assertEqual(resolve_palette("auto", date(year, 12, 31)), "default")
            for day in (24, 25, 26):
                self.assertEqual(resolve_palette("auto", date(year, 12, day)), "christmas")
            self.assertEqual(resolve_palette("auto", date(year, 12, 27)), "default")
        self.assertEqual(resolve_palette("newyear", date(2026, 1, 2)), "newyear")
        self.assertEqual(resolve_palette("newyear", date(2026, 12, 31)), "newyear")
        self.assertEqual(resolve_palette("newyear", date(2026, 12, 25)), "newyear")
        self.assertEqual(resolve_palette("default", date(2026, 1, 1)), "default")
        self.assertEqual(resolve_palette("christmas", date(2026, 1, 1)), "christmas")

    def test_auto_palette_is_valentine_only_on_february_14(self) -> None:
        """14 February is valentine, except on a dual-festival overlap.

        2029-02-14 falls in the Lunar New Year window, so auto fades from
        lunarnewyear to valentine. 2032-02-14 is the day after that year's
        window (11-13 February), so it is plain valentine. Forcing
        ``valentine`` does not follow the date.
        """
        fade = PaletteTransition("lunarnewyear", "valentine")
        for year in (2020, 2024, 2025, 2026, 2028, 2032, 2036):
            self.assertEqual(resolve_palette("auto", date(year, 2, 14)), "valentine")
        self.assertEqual(resolve_palette("auto", date(2026, 2, 13)), "default")
        self.assertEqual(resolve_palette("auto", date(2026, 2, 15)), "default")
        self.assertEqual(resolve_palette("auto", date(2029, 2, 12)), "default")
        self.assertEqual(resolve_palette("auto", date(2029, 2, 13)), "lunarnewyear")
        self.assertEqual(resolve_palette("auto", date(2029, 2, 14)), fade)
        self.assertEqual(resolve_palette("auto", date(2029, 2, 15)), "lunarnewyear")
        self.assertEqual(resolve_palette("auto", date(2029, 2, 16)), "default")
        self.assertEqual(resolve_palette("auto", date(2032, 2, 13)), "lunarnewyear")
        self.assertEqual(resolve_palette("auto", date(2032, 2, 14)), "valentine")
        self.assertEqual(resolve_palette("valentine", date(2026, 2, 15)), "valentine")
        self.assertEqual(resolve_palette("valentine", date(2026, 12, 25)), "valentine")
        self.assertEqual(resolve_palette("default", date(2026, 2, 14)), "default")
        self.assertEqual(resolve_palette("lunarnewyear", date(2029, 2, 14)), "lunarnewyear")
        self.assertEqual(resolve_palette("newyear", date(2026, 2, 14)), "newyear")
        self.assertEqual(resolve_palette("lunarnewyear>valentine", date(2026, 2, 14)), fade)

    def test_auto_palette_is_lunar_new_year_on_the_festival_and_the_next_two_days(self) -> None:
        """The tabulated UTC day and the two days after it select lunarnewyear.

        Christmas is three days, so Lunar New Year uses that same length.
        1 January stays newyear. When 14 February falls inside the
        window, auto fades from lunarnewyear to valentine instead of
        picking only one palette. The day before the window and the day
        after it stay on the green graph, except when that day is
        Valentine's Day. 2025 and 2036 are outside the table, including
        29 January 2025, which is that year's Lunar New Year.
        """
        self.assertEqual(LUNAR_NEW_YEAR_SPAN_DAYS, 3)
        self.assertEqual(
            LUNAR_NEW_YEAR_DATES,
            (
                date(2026, 2, 17),
                date(2027, 2, 6),
                date(2028, 1, 26),
                date(2029, 2, 13),
                date(2030, 2, 3),
                date(2031, 1, 23),
                date(2032, 2, 11),
                date(2033, 1, 31),
                date(2034, 2, 19),
                date(2035, 2, 8),
            ),
        )
        for anchor in LUNAR_NEW_YEAR_DATES:
            self.assertEqual(resolve_palette("auto", date(anchor.year, 1, 1)), "newyear", anchor)
            self.assertEqual(resolve_palette("auto", date(anchor.year, 1, 2)), "default", anchor)
            before = anchor - timedelta(days=1)
            if (before.month, before.day) == VALENTINE_DAY:
                self.assertEqual(resolve_palette("auto", before), "valentine", before)
            else:
                self.assertEqual(resolve_palette("auto", before), "default", before)
            for offset in range(LUNAR_NEW_YEAR_SPAN_DAYS):
                day = anchor + timedelta(days=offset)
                self.assertNotEqual((day.month, day.day), (1, 1), day)
                if (day.month, day.day) == VALENTINE_DAY:
                    self.assertEqual(
                        resolve_palette("auto", day),
                        PaletteTransition("lunarnewyear", "valentine"),
                        day,
                    )
                else:
                    self.assertEqual(resolve_palette("auto", day), "lunarnewyear", day)
            after = anchor + timedelta(days=LUNAR_NEW_YEAR_SPAN_DAYS)
            if (after.month, after.day) == VALENTINE_DAY:
                self.assertEqual(resolve_palette("auto", after), "valentine", after)
            else:
                self.assertEqual(resolve_palette("auto", after), "default", after)
        # 2033 starts on 31 January, so the window crosses into February.
        self.assertEqual(resolve_palette("auto", date(2033, 1, 30)), "default")
        self.assertEqual(resolve_palette("auto", date(2033, 1, 31)), "lunarnewyear")
        self.assertEqual(resolve_palette("auto", date(2033, 2, 1)), "lunarnewyear")
        self.assertEqual(resolve_palette("auto", date(2033, 2, 2)), "lunarnewyear")
        self.assertEqual(resolve_palette("auto", date(2033, 2, 3)), "default")
        self.assertEqual(resolve_palette("auto", date(2033, 1, 1)), "newyear")
        self.assertEqual(resolve_palette("auto", date(2025, 2, 14)), "valentine")
        self.assertEqual(resolve_palette("auto", date(2036, 2, 14)), "valentine")
        # Same month-day in a year the table does not list stays green.
        # 29 January 2025 is Lunar New Year for 2025.
        for outside in (
            date(2025, 1, 29),
            date(2025, 2, 17),
            date(2024, 2, 10),
            date(2036, 1, 23),
            date(2036, 1, 31),
            date(2036, 2, 8),
            date(2036, 2, 17),
        ):
            self.assertEqual(resolve_palette("auto", outside), "default", outside)
        self.assertEqual(resolve_palette("lunarnewyear", date(2025, 1, 29)), "lunarnewyear")
        self.assertEqual(resolve_palette("default", date(2026, 2, 17)), "default")
        self.assertEqual(resolve_palette("newyear", date(2026, 2, 17)), "newyear")
        self.assertEqual(resolve_palette("auto", date(2028, 2, 29)), "default")
        for year in (2025, 2026, 2029, 2032, 2033, 2036):
            day = date(year, 1, 1)
            while day.year == year:
                self.assertEqual(resolve_palette("auto", day), _auto_choice(day), day.isoformat())
                day += timedelta(days=1)

    def test_auto_palette_follows_the_catalog_across_the_year(self) -> None:
        """Every UTC day of a common year and a leap year matches the catalog.

        31 October is halloween. 24-26 December is christmas. 1 January is
        newyear. 14 February is valentine, except a year when it also
        falls in the Lunar New Year window. 2023 and 2024 are outside
        the Lunar New Year table, so 31 December, 2 January, and 29
        February stay on the green graph.
        """
        lunar_dates = _lunar_window()
        self.assertEqual(
            [(name, spec.auto_days, spec.auto_dates) for name, spec in PALETTE_CATALOG],
            [
                ("default", (), ()),
                ("halloween", ((10, 31),), ()),
                ("christmas", ((12, 24), (12, 25), (12, 26)), ()),
                ("newyear", ((1, 1),), ()),
                ("valentine", (VALENTINE_DAY,), ()),
                ("lunarnewyear", (), lunar_dates),
            ],
        )
        self.assertEqual(
            PALETTE_NAMES,
            ("default", "halloween", "christmas", "newyear", "valentine", "lunarnewyear", "auto"),
        )
        self.assertEqual(
            AUTO_HOLIDAYS,
            (
                ("halloween", ((10, 31),), ()),
                ("christmas", ((12, 24), (12, 25), (12, 26)), ()),
                ("newyear", ((1, 1),), ()),
                ("valentine", (VALENTINE_DAY,), ()),
                ("lunarnewyear", (), lunar_dates),
            ),
        )
        self.assertIs(PALETTE_TABLES["default"], PALETTES)
        self.assertIs(PALETTE_TABLES["halloween"], HALLOWEEN_PALETTES)
        self.assertIs(PALETTE_TABLES["christmas"], CHRISTMAS_PALETTES)
        self.assertIs(PALETTE_TABLES["newyear"], NEWYEAR_PALETTES)
        self.assertIs(PALETTE_TABLES["valentine"], VALENTINE_PALETTES)
        self.assertIs(PALETTE_TABLES["lunarnewyear"], LUNAR_NEW_YEAR_PALETTES)
        self.assertEqual(format_auto_days(((10, 31),)), "31 October")
        self.assertEqual(format_auto_days(((12, 26), (12, 24), (12, 25))), "24-26 December")
        self.assertEqual(
            format_auto_days(((12, 24), (12, 26))),
            "24 December and 26 December",
        )
        self.assertEqual(format_auto_dates((date(2026, 2, 17),)), "17 February 2026")
        self.assertEqual(
            format_auto_dates((date(2026, 2, 19), date(2026, 2, 17), date(2026, 2, 18))),
            "17-19 February 2026",
        )
        self.assertEqual(
            format_auto_dates((date(2033, 1, 31), date(2033, 2, 1), date(2033, 2, 2))),
            "31 January-2 February 2033",
        )
        self.assertEqual(
            format_auto_dates((date(2035, 12, 31), date(2036, 1, 1), date(2036, 1, 2))),
            "31 December 2035-2 January 2036",
        )
        self.assertEqual(
            format_auto_dates((date(2026, 2, 17), date(2026, 2, 19))),
            "17 February 2026 and 19 February 2026",
        )
        with self.assertRaises(ValueError):
            format_auto_dates(())
        rules = {
            (month, day): name
            for name, spec in PALETTE_CATALOG
            for month, day in spec.auto_days
        }
        for year in (2023, 2024):
            day = date(year, 1, 1)
            last = date(year, 12, 31)
            while day <= last:
                expected = rules.get((day.month, day.day), "default")
                self.assertEqual(resolve_palette("auto", day), expected, day.isoformat())
                for concrete in ("default", "halloween", "christmas", "newyear", "valentine", "lunarnewyear"):
                    self.assertEqual(resolve_palette(concrete, day), concrete, day.isoformat())
                day += timedelta(days=1)
        self.assertEqual(resolve_palette("auto", date(2024, 2, 29)), "default")
        for year in (2020, 2023, 2024, 2026, 2028):
            self.assertEqual(resolve_palette("auto", date(year, 12, 31)), "default")
            self.assertEqual(resolve_palette("auto", date(year + 1, 1, 1)), "newyear")
            self.assertEqual(resolve_palette("auto", date(year + 1, 1, 2)), "default")

    def test_catalog_keeps_the_default_empty_cell_on_every_palette(self) -> None:
        """Level 0 stays the default empty cell. A drifted holiday is rejected."""
        _validate_palette_catalog(PALETTE_CATALOG)
        default = PALETTE_CATALOG[0][1]
        self.assertEqual(default.themes["light"]["levels"][0], "#eff2f5")
        self.assertEqual(default.themes["dark"]["levels"][0], "#151b23")
        for name, spec in PALETTE_CATALOG:
            for theme in ("light", "dark"):
                self.assertEqual(
                    spec.themes[theme]["levels"][0],
                    default.themes[theme]["levels"][0],
                    f"{name} {theme}",
                )

        halloween = PALETTE_CATALOG[1][1]
        themes = {theme: dict(colors) for theme, colors in halloween.themes.items()}
        themes["light"]["levels"] = ("#ffffff",) + tuple(themes["light"]["levels"][1:])
        drifted = PaletteSpec(themes, "a holiday with a white empty cell", ((6, 1),))
        with self.assertRaises(ValueError) as caught:
            _validate_palette_catalog((("default", default), ("midsummer", drifted)))
        message = str(caught.exception)
        self.assertIn("midsummer", message)
        self.assertIn("light", message)
        self.assertIn("#ffffff", message)
        self.assertIn("#eff2f5", message)

    def test_catalog_rejects_a_holiday_that_cannot_be_selected(self) -> None:
        """Overlapping days, impossible dates, and a dated default fail while loading."""
        default = PALETTE_CATALOG[0][1]
        halloween = PALETTE_CATALOG[1][1]
        christmas = PALETTE_CATALOG[2][1]
        overlapping = PaletteSpec(christmas.themes, christmas.summary, ((10, 31),))
        with self.assertRaises(ValueError) as caught:
            _validate_palette_catalog(
                (
                    ("default", default),
                    ("halloween", halloween),
                    ("christmas", overlapping),
                )
            )
        message = str(caught.exception)
        self.assertIn("(10, 31)", message)
        self.assertIn("halloween", message)
        self.assertIn("christmas", message)
        self.assertIn("one palette", message)

        impossible = PaletteSpec(halloween.themes, halloween.summary, ((2, 30),))
        with self.assertRaises(ValueError) as caught:
            _validate_palette_catalog((("default", default), ("halloween", impossible)))
        self.assertIn("(2, 30)", str(caught.exception))
        self.assertIn("not a calendar day", str(caught.exception))

        # 29 February exists, so a leap-day holiday is a real date.
        leap_day = PaletteSpec(halloween.themes, halloween.summary, ((2, 29),))
        _validate_palette_catalog((("default", default), ("halloween", leap_day)))

        dated_default = PaletteSpec(default.themes, default.summary, ((1, 1),))
        with self.assertRaises(ValueError) as caught:
            _validate_palette_catalog((("default", dated_default),))
        self.assertIn("default", str(caught.exception))

        dated_default_year = PaletteSpec(default.themes, default.summary, auto_dates=(date(2026, 2, 17),))
        with self.assertRaises(ValueError) as caught:
            _validate_palette_catalog((("default", dated_default_year),))
        self.assertIn("default", str(caught.exception))

        with self.assertRaises(ValueError) as caught:
            _validate_palette_catalog((("default", default), ("auto", halloween)))
        self.assertIn("selector", str(caught.exception))

        newyear = PALETTE_CATALOG[3][1]
        on_new_year = PaletteSpec(halloween.themes, "a moved holiday", auto_dates=(date(2031, 1, 1),))
        with self.assertRaises(ValueError) as caught:
            _validate_palette_catalog(
                (("default", default), ("newyear", newyear), ("clash", on_new_year))
            )
        message = str(caught.exception)
        self.assertIn("2031-01-01", message)
        self.assertIn("newyear", message)
        self.assertIn("one palette", message)

        # A Chinese festival may share a date with a Western holiday.
        lunar = PALETTE_CATALOG[5][1]
        overlapping = PaletteSpec(
            lunar.themes,
            lunar.summary,
            auto_dates=(date(2029, 2, 14),),
            tradition="chinese",
        )
        valentine = PALETTE_CATALOG[4][1]
        day_fades, date_fades = _validate_palette_catalog(
            (("default", default), ("valentine", valentine), ("lunarnewyear", overlapping))
        )
        self.assertEqual(date_fades[date(2029, 2, 14)], PaletteTransition("lunarnewyear", "valentine"))
        self.assertFalse(day_fades)

        repeated = PaletteSpec(
            halloween.themes,
            "a moved holiday",
            auto_dates=(date(2026, 2, 17), date(2026, 2, 17)),
        )
        with self.assertRaises(ValueError) as caught:
            _validate_palette_catalog((("default", default), ("twice", repeated)))
        self.assertIn("2026-02-17", str(caught.exception))

        # A year-specific day registered before the repeating holiday still clashes.
        earlier = PaletteSpec(halloween.themes, "a moved holiday", auto_dates=(date(2026, 10, 31),))
        with self.assertRaises(ValueError) as caught:
            _validate_palette_catalog(
                (("default", default), ("earlier", earlier), ("halloween", halloween))
            )
        self.assertIn("2026-10-31", str(caught.exception))
        self.assertIn("halloween", str(caught.exception))

        bad_date = PaletteSpec(halloween.themes, "bad date", auto_dates=("2026-02-17",))  # type: ignore[arg-type]
        with self.assertRaises(ValueError) as caught:
            _validate_palette_catalog((("default", default), ("bad", bad_date)))
        self.assertIn("not a calendar date", str(caught.exception))

    def test_help_names_every_catalog_auto_date(self) -> None:
        proc = _run_generate(["--help"], env=os.environ.copy())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # argparse wraps the help line, so compare the words with the breaks gone.
        text = " ".join(proc.stdout.split())
        expected = " ".join(palette_cli_help().split())
        self.assertIn(expected, text)
        for name, spec in PALETTE_CATALOG:
            self.assertIn(name, text)
            if spec.auto_days:
                self.assertIn(format_auto_days(spec.auto_days), text)
            if spec.auto_dates:
                self.assertIn(format_auto_dates(spec.auto_dates), text)
        self.assertIn("auto", text)

    def test_halloween_colors_replace_green_levels_and_default_svg_is_unchanged(self) -> None:
        """Primer Halloween levels 1-4, with the default empty cell left in place.

        Omitting the palette paints the same SVG as palette ``default``.
        """
        calendar = _tiny_calendar()
        pieces = pieces_for_calendar(calendar)
        for theme in ("light", "dark"):
            plain = render_svg(calendar, pieces, theme)
            explicit = render_svg(calendar, pieces, theme, palette="default")
            halloween = render_svg(calendar, pieces, theme, palette="halloween")
            self.assertEqual(plain, explicit)
            self.assertNotEqual(plain, halloween)
            green = PALETTES[theme]["levels"]
            orange = HALLOWEEN_PALETTES[theme]["levels"]
            # @primer/primitives 11.10.0, --contribution-halloween-bgColor-1..4.
            # Level 0 stays --contribution-default-bgColor-0.
            expected = {
                "light": ("#eff2f5", "#f0db3d", "#ffd642", "#f68c41", "#1f2328"),
                "dark": ("#151b23", "#fac68f", "#c46212", "#984b10", "#e3d04f"),
            }
            self.assertEqual(orange, expected[theme])
            self.assertEqual(green[0], orange[0])
            self.assertIn(f'fill="{green[0]}"', halloween)
            for level in range(1, 5):
                self.assertIn(f'fill="{orange[level]}"', halloween)
                self.assertNotIn(f'fill="{green[level]}"', halloween)
                self.assertIn(f'fill="{green[level]}"', plain)
            self.assertIn('href="#b' + theme[0], halloween)
        with self.assertRaises(ValueError):
            render_svg(calendar, pieces, "light", palette="auto")

    def test_christmas_colors_are_five_levels_with_a_neutral_empty_cell(self) -> None:
        """Coolors Christmas levels 1-4, with the default empty cell left in place.

        Levels are ordered by contrast with the empty cell. Each active level
        clears that background, and neighboring levels stay far enough apart
        to tell apart. The red sits beside the darkest green, which is the
        smallest step.
        """
        calendar = _tiny_calendar()
        pieces = pieces_for_calendar(calendar)
        expected = {
            "light": ("#eff2f5", "#a7c957", "#6a994e", "#bc4749", "#386641"),
            "dark": ("#151b23", "#386641", "#bc4749", "#6a994e", "#a7c957"),
        }
        for theme in ("light", "dark"):
            plain = render_svg(calendar, pieces, theme)
            christmas = render_svg(calendar, pieces, theme, palette="christmas")
            self.assertNotEqual(plain, christmas)
            green = PALETTES[theme]["levels"]
            festive = CHRISTMAS_PALETTES[theme]["levels"]
            self.assertEqual(festive, expected[theme])
            self.assertEqual(len(festive), 5)
            self.assertEqual(len(set(festive)), 5)
            self.assertEqual(green[0], festive[0])
            self.assertIn(f'fill="{green[0]}"', christmas)
            for level in range(1, 5):
                self.assertGreaterEqual(_contrast(festive[level], festive[0]), 1.45)
                self.assertGreaterEqual(_contrast(festive[level], festive[level - 1]), 1.30)
                self.assertIn(f'fill="{festive[level]}"', christmas)
                self.assertNotIn(f'fill="{green[level]}"', christmas)
                self.assertNotEqual(festive[level], HALLOWEEN_PALETTES[theme]["levels"][level])
            self.assertIn('href="#b' + theme[0], christmas)

    def test_newyear_colors_are_the_color_hunt_gold_scale(self) -> None:
        """Color Hunt gold levels 1-4, with the default empty cell left in place.

        The four source colors are used exactly, ordered by contrast against
        the empty cell. Christmas and Halloween colors stay off this graph.
        """
        calendar = _tiny_calendar()
        pieces = pieces_for_calendar(calendar)
        expected = {
            "light": ("#eff2f5", "#f9e6a8", "#f2a900", "#cc6f00", "#4d2a00"),
            "dark": ("#151b23", "#4d2a00", "#cc6f00", "#f2a900", "#f9e6a8"),
        }
        source = ("#f9e6a8", "#f2a900", "#cc6f00", "#4d2a00")
        for theme in ("light", "dark"):
            plain = render_svg(calendar, pieces, theme)
            newyear = render_svg(calendar, pieces, theme, palette="newyear")
            self.assertNotEqual(plain, newyear)
            green = PALETTES[theme]["levels"]
            gold = NEWYEAR_PALETTES[theme]["levels"]
            self.assertEqual(gold, expected[theme])
            self.assertEqual(gold[1:], source if theme == "light" else tuple(reversed(source)))
            self.assertEqual(len(gold), 5)
            self.assertEqual(len(set(gold)), 5)
            self.assertEqual(green[0], gold[0])
            self.assertIn(f'fill="{green[0]}"', newyear)
            previous = 0.0
            for level in range(1, 5):
                ratio = _contrast(gold[level], gold[0])
                self.assertGreater(ratio, previous)
                previous = ratio
                self.assertIn(f'fill="{gold[level]}"', newyear)
                self.assertNotIn(f'fill="{green[level]}"', newyear)
                self.assertNotEqual(gold[level], HALLOWEEN_PALETTES[theme]["levels"][level])
                self.assertNotEqual(gold[level], CHRISTMAS_PALETTES[theme]["levels"][level])
            self.assertIn('href="#b' + theme[0], newyear)

    def test_valentine_colors_are_the_schemecolor_hearts_scale(self) -> None:
        """SchemeColor Valentine's Hearts levels 1-4, lightest to darkest.

        The four source colors are used exactly. Light runs lightest to
        darkest and dark runs the other way. Level 0 stays the empty
        cell. The other holiday colors stay off this graph.
        """
        calendar = _tiny_calendar()
        pieces = pieces_for_calendar(calendar)
        expected = {
            "light": ("#eff2f5", "#f7aee8", "#fd647c", "#f6383a", "#d81a37"),
            "dark": ("#151b23", "#d81a37", "#f6383a", "#fd647c", "#f7aee8"),
        }
        source = ("#f7aee8", "#fd647c", "#f6383a", "#d81a37")
        for theme in ("light", "dark"):
            plain = render_svg(calendar, pieces, theme)
            valentine = render_svg(calendar, pieces, theme, palette="valentine")
            self.assertNotEqual(plain, valentine)
            green = PALETTES[theme]["levels"]
            hearts = VALENTINE_PALETTES[theme]["levels"]
            self.assertEqual(hearts, expected[theme])
            self.assertEqual(hearts[1:], source if theme == "light" else tuple(reversed(source)))
            self.assertEqual(len(hearts), 5)
            self.assertEqual(len(set(hearts)), 5)
            self.assertEqual(green[0], hearts[0])
            self.assertEqual(VALENTINE_PALETTES[theme]["text"], PALETTES[theme]["text"])
            self.assertEqual(VALENTINE_PALETTES[theme]["border"], PALETTES[theme]["border"])
            self.assertIn(f'fill="{green[0]}"', valentine)
            for level in range(1, 5):
                self.assertIn(f'fill="{hearts[level]}"', valentine)
                self.assertNotIn(f'fill="{green[level]}"', valentine)
                self.assertNotEqual(hearts[level], HALLOWEEN_PALETTES[theme]["levels"][level])
                self.assertNotEqual(hearts[level], CHRISTMAS_PALETTES[theme]["levels"][level])
                self.assertNotEqual(hearts[level], NEWYEAR_PALETTES[theme]["levels"][level])
                self.assertNotEqual(hearts[level], LUNAR_NEW_YEAR_PALETTES[theme]["levels"][level])
            self.assertIn('href="#b' + theme[0], valentine)

    def test_overlap_fade_starts_on_lunar_new_year_and_ends_on_valentine(self) -> None:
        """A shared UTC day paints both scales and a tone fade in the SVG.

        2029-02-14 is the only overlap in the 2026-2035 table. 2032-02-14
        is the day after that year's window, so it stays plain valentine.
        Reduced motion keeps the Western end state. An explicit
        ``lunarnewyear>valentine`` fade works on any day.
        """
        calendar = _tiny_calendar()
        pieces = pieces_for_calendar(calendar)
        fade = PaletteTransition("lunarnewyear", "valentine")
        self.assertEqual(str(fade), "lunarnewyear>valentine")
        self.assertEqual(resolve_palette("auto", date(2029, 2, 14)), fade)
        self.assertEqual(resolve_palette("auto", date(2032, 2, 14)), "valentine")
        self.assertEqual(AUTO_TRANSITIONS_DATES[date(2029, 2, 14)], fade)
        self.assertNotIn(date(2032, 2, 14), AUTO_TRANSITIONS_DATES)
        self.assertFalse(AUTO_TRANSITIONS_DAYS)
        for theme in ("light", "dark"):
            svg = render_svg(calendar, pieces, theme, palette=fade)
            lunar = render_svg(calendar, pieces, theme, palette="lunarnewyear")
            valentine = render_svg(calendar, pieces, theme, palette="valentine")
            self.assertNotEqual(svg, lunar)
            self.assertNotEqual(svg, valentine)
            for color in LUNAR_NEW_YEAR_PALETTES[theme]["levels"][1:]:
                self.assertIn(f'fill="{color}"', svg)
            for color in VALENTINE_PALETTES[theme]["levels"][1:]:
                self.assertIn(f'fill="{color}"', svg)
            self.assertIn("tone-start", svg)
            self.assertIn("tone-end", svg)
            self.assertIn("@keyframes tone-start", svg)
            self.assertIn("@keyframes tone-end", svg)
            self.assertIn("prefers-reduced-motion", svg)
            self.assertIn(".tone-start{opacity:0}", svg)
            self.assertIn(".tone-end{opacity:1}", svg)
            # Empty cells stay the shared neutral and are not faded.
            self.assertIn(f'href="#b{theme[0]}0"', svg)
            self.assertNotIn(f'href="#b{theme[0]}0e"', svg)
        explicit = render_svg(calendar, pieces, "light", palette="lunarnewyear>valentine")
        # resolve_palette returns the same fade object values; render_svg
        # accepts the string form too via generate, but here pass the object.
        self.assertIn("tone-start", explicit)
        # Passing the resolved auto result for 2029 must match the explicit fade.
        auto = render_svg(calendar, pieces, "light", palette=resolve_palette("auto", date(2029, 2, 14)))
        self.assertEqual(auto, render_svg(calendar, pieces, "light", palette=fade))
        plain_valentine = render_svg(
            calendar, pieces, "light", palette=resolve_palette("auto", date(2032, 2, 14))
        )
        self.assertEqual(plain_valentine, render_svg(calendar, pieces, "light", palette="valentine"))
        self.assertNotIn("tone-start", plain_valentine)

    def test_lunar_new_year_colors_are_the_schemecolor_gold_and_red(self) -> None:
        """SchemeColor Chinese Gold & Red levels 1-4, lightest to darkest.

        The four kept source colors are used exactly. Scarlett and Chinese
        Gold are not in the scale. Light runs lightest to darkest and dark
        runs the other way. Level 0 stays the empty cell. The other holiday
        colors stay off this graph.
        """
        calendar = _tiny_calendar()
        pieces = pieces_for_calendar(calendar)
        expected = {
            "light": ("#eff2f5", "#ebc862", "#e4b034", "#c50100", "#830010"),
            "dark": ("#151b23", "#830010", "#c50100", "#e4b034", "#ebc862"),
        }
        source = ("#ebc862", "#e4b034", "#c50100", "#830010")
        for theme in ("light", "dark"):
            plain = render_svg(calendar, pieces, theme)
            lunar = render_svg(calendar, pieces, theme, palette="lunarnewyear")
            self.assertNotEqual(plain, lunar)
            green = PALETTES[theme]["levels"]
            festive = LUNAR_NEW_YEAR_PALETTES[theme]["levels"]
            self.assertEqual(festive, expected[theme])
            self.assertEqual(festive[1:], source if theme == "light" else tuple(reversed(source)))
            self.assertEqual(len(festive), 5)
            self.assertEqual(len(set(festive)), 5)
            for dropped in ("#960316", "#ca9d08", "#fef3e2", "#fab12f", "#fa812f", "#dd0303"):
                self.assertNotIn(dropped, festive)
            self.assertEqual(green[0], festive[0])
            self.assertEqual(LUNAR_NEW_YEAR_PALETTES[theme]["text"], PALETTES[theme]["text"])
            self.assertEqual(LUNAR_NEW_YEAR_PALETTES[theme]["border"], PALETTES[theme]["border"])
            self.assertIn(f'fill="{green[0]}"', lunar)
            for level in range(1, 5):
                self.assertIn(f'fill="{festive[level]}"', lunar)
                self.assertNotIn(f'fill="{green[level]}"', lunar)
                self.assertNotEqual(festive[level], HALLOWEEN_PALETTES[theme]["levels"][level])
                self.assertNotEqual(festive[level], CHRISTMAS_PALETTES[theme]["levels"][level])
                self.assertNotEqual(festive[level], NEWYEAR_PALETTES[theme]["levels"][level])
                self.assertNotEqual(festive[level], VALENTINE_PALETTES[theme]["levels"][level])
            self.assertIn('href="#b' + theme[0], lunar)

    def test_cli_palette_flag_selects_halloween_without_changing_the_default(self) -> None:
        import json

        payload = _json_calendar(
            "demo",
            date(2026, 10, 11),
            date(2026, 10, 17),
            {date(2026, 10, 12): (3, 2)},
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "calendar.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            env = os.environ.copy()
            written: dict[str, tuple[str, str]] = {}
            for name, extra in (
                ("omit", []),
                ("default", ["--palette", "default"]),
                ("halloween", ["--palette", "Halloween"]),
            ):
                folder = Path(tmp) / name
                proc = _run_generate(
                    ["--input", str(source), "--out", str(folder), "--seed", "0", *extra],
                    env=env,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                written[name] = (
                    (folder / "tetris-contrib.svg").read_text(encoding="utf-8"),
                    (folder / "tetris-contrib-dark.svg").read_text(encoding="utf-8"),
                )
            self.assertEqual(written["omit"], written["default"])
            light, dark = written["halloween"]
            self.assertIn('fill="#f0db3d"', light)
            self.assertIn('fill="#1f2328"', light)
            self.assertNotIn('fill="#aceebb"', light)
            self.assertIn('fill="#fac68f"', dark)
            self.assertIn('fill="#e3d04f"', dark)
            self.assertNotIn('fill="#56d364"', dark)
            self.assertNotEqual(written["omit"], written["halloween"])
            action = (ROOT / "action.yml").read_text(encoding="utf-8")
            self.assertIn("\n  palette:\n", action)
            self.assertIn("TETRIS_PALETTE: ${{ inputs.palette }}", action)
            self.assertIn('--palette "${TETRIS_PALETTE-default}"', action)

    def test_cli_palette_flag_selects_christmas(self) -> None:
        import json

        payload = _json_calendar(
            "demo",
            date(2026, 10, 11),
            date(2026, 10, 17),
            {date(2026, 10, 12): (3, 2)},
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "calendar.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            folder = Path(tmp) / "christmas"
            proc = _run_generate(
                [
                    "--input",
                    str(source),
                    "--out",
                    str(folder),
                    "--seed",
                    "0",
                    "--palette",
                    "Christmas",
                ],
                env=os.environ.copy(),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            light = (folder / "tetris-contrib.svg").read_text(encoding="utf-8")
            dark = (folder / "tetris-contrib-dark.svg").read_text(encoding="utf-8")
            self.assertIn('fill="#a7c957"', light)
            self.assertIn('fill="#6a994e"', light)
            self.assertIn('fill="#bc4749"', light)
            self.assertIn('fill="#386641"', light)
            self.assertIn('fill="#eff2f5"', light)
            self.assertNotIn('fill="#aceebb"', light)
            self.assertIn('fill="#386641"', dark)
            self.assertIn('fill="#bc4749"', dark)
            self.assertIn('fill="#6a994e"', dark)
            self.assertIn('fill="#a7c957"', dark)
            self.assertIn('fill="#151b23"', dark)
            self.assertNotIn('fill="#56d364"', dark)
            action = (ROOT / "action.yml").read_text(encoding="utf-8")
            self.assertIn("christmas", action)
            self.assertIn("24-26 December", action)

    def test_cli_palette_flag_selects_newyear(self) -> None:
        import json

        payload = _json_calendar(
            "demo",
            date(2026, 10, 11),
            date(2026, 10, 17),
            {date(2026, 10, 12): (3, 2)},
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "calendar.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            folder = Path(tmp) / "newyear"
            proc = _run_generate(
                [
                    "--input",
                    str(source),
                    "--out",
                    str(folder),
                    "--seed",
                    "0",
                    "--palette",
                    "NewYear",
                ],
                env=os.environ.copy(),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            light = (folder / "tetris-contrib.svg").read_text(encoding="utf-8")
            dark = (folder / "tetris-contrib-dark.svg").read_text(encoding="utf-8")
            for color in ("#f9e6a8", "#f2a900", "#cc6f00", "#4d2a00"):
                self.assertIn(f'fill="{color}"', light)
                self.assertIn(f'fill="{color}"', dark)
            self.assertIn('fill="#eff2f5"', light)
            self.assertIn('fill="#151b23"', dark)
            self.assertNotIn('fill="#aceebb"', light)
            self.assertNotIn('fill="#a7c957"', light)
            self.assertNotIn('fill="#56d364"', dark)
            self.assertNotIn('fill="#bc4749"', dark)
            action = (ROOT / "action.yml").read_text(encoding="utf-8")
            self.assertIn("newyear", action)
            self.assertIn("1 January", action)
            self.assertIn("TETRIS_PALETTE: ${{ inputs.palette }}", action)
            self.assertIn('--palette "${TETRIS_PALETTE-default}"', action)

    def test_cli_palette_flag_selects_lunar_new_year(self) -> None:
        import json

        payload = _json_calendar(
            "demo",
            date(2026, 10, 11),
            date(2026, 10, 17),
            {date(2026, 10, 12): (3, 2)},
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "calendar.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            folder = Path(tmp) / "lunarnewyear"
            proc = _run_generate(
                [
                    "--input",
                    str(source),
                    "--out",
                    str(folder),
                    "--seed",
                    "0",
                    "--palette",
                    "LunarNewYear",
                ],
                env=os.environ.copy(),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            light = (folder / "tetris-contrib.svg").read_text(encoding="utf-8")
            dark = (folder / "tetris-contrib-dark.svg").read_text(encoding="utf-8")
            for color in ("#ebc862", "#e4b034", "#c50100", "#830010"):
                self.assertIn(f'fill="{color}"', light)
                self.assertIn(f'fill="{color}"', dark)
            for dropped in ("#960316", "#ca9d08", "#fef3e2", "#fab12f", "#fa812f", "#dd0303"):
                self.assertNotIn(f'fill="{dropped}"', light)
                self.assertNotIn(f'fill="{dropped}"', dark)
            self.assertIn('fill="#eff2f5"', light)
            self.assertIn('fill="#151b23"', dark)
            self.assertNotIn('fill="#aceebb"', light)
            self.assertNotIn('fill="#f9e6a8"', light)
            self.assertNotIn('fill="#a7c957"', light)
            self.assertNotIn('fill="#56d364"', dark)
            self.assertNotIn('fill="#4d2a00"', dark)
            action = (ROOT / "action.yml").read_text(encoding="utf-8")
            self.assertIn("lunarnewyear", action)
            self.assertIn("17-19 February 2026", action)
            self.assertIn("https://www.schemecolor.com/chinese-gold-red.php", action)
            readme = (ROOT / "README.md").read_text(encoding="utf-8")
            self.assertIn("lunarnewyear", readme)
            self.assertIn("https://www.schemecolor.com/chinese-gold-red.php", readme)
            self.assertIn("2026-02-17", readme)
            self.assertIn("2035-02-08", readme)

    def test_cli_palette_flag_selects_valentine(self) -> None:
        import json

        payload = _json_calendar(
            "demo",
            date(2026, 10, 11),
            date(2026, 10, 17),
            {date(2026, 10, 12): (3, 2)},
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "calendar.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            folder = Path(tmp) / "valentine"
            proc = _run_generate(
                [
                    "--input",
                    str(source),
                    "--out",
                    str(folder),
                    "--seed",
                    "0",
                    "--palette",
                    "Valentine",
                ],
                env=os.environ.copy(),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            light = (folder / "tetris-contrib.svg").read_text(encoding="utf-8")
            dark = (folder / "tetris-contrib-dark.svg").read_text(encoding="utf-8")
            for color in ("#f7aee8", "#fd647c", "#f6383a", "#d81a37"):
                self.assertIn(f'fill="{color}"', light)
                self.assertIn(f'fill="{color}"', dark)
            self.assertIn('fill="#eff2f5"', light)
            self.assertIn('fill="#151b23"', dark)
            self.assertNotIn('fill="#aceebb"', light)
            self.assertNotIn('fill="#ebc862"', light)
            self.assertNotIn('fill="#f9e6a8"', light)
            self.assertNotIn('fill="#a7c957"', light)
            self.assertNotIn('fill="#56d364"', dark)
            self.assertNotIn('fill="#4d2a00"', dark)
            self.assertNotIn('fill="#830010"', dark)
            action = (ROOT / "action.yml").read_text(encoding="utf-8")
            self.assertIn("valentine", action)
            self.assertIn("14 February", action)
            self.assertIn("https://www.schemecolor.com/valentines-hearts.php", action)
            readme = (ROOT / "README.md").read_text(encoding="utf-8")
            self.assertIn("valentine", readme)
            self.assertIn("https://www.schemecolor.com/valentines-hearts.php", readme)
            self.assertIn("#f7aee8", readme)
            self.assertIn("#d81a37", readme)

    def test_cli_palette_flag_selects_a_fade(self) -> None:
        import json

        payload = _json_calendar(
            "demo",
            date(2026, 10, 11),
            date(2026, 10, 17),
            {date(2026, 10, 12): (3, 2)},
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "calendar.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            folder = Path(tmp) / "fade"
            proc = _run_generate(
                [
                    "--input",
                    str(source),
                    "--out",
                    str(folder),
                    "--seed",
                    "0",
                    "--palette",
                    "LunarNewYear>Valentine",
                ],
                env=os.environ.copy(),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            light = (folder / "tetris-contrib.svg").read_text(encoding="utf-8")
            dark = (folder / "tetris-contrib-dark.svg").read_text(encoding="utf-8")
            for svg in (light, dark):
                self.assertIn("tone-start", svg)
                self.assertIn("@keyframes tone-end", svg)
            for color in ("#ebc862", "#c50100", "#f7aee8", "#d81a37"):
                self.assertIn(f'fill="{color}"', light)
                self.assertIn(f'fill="{color}"', dark)
            action = (ROOT / "action.yml").read_text(encoding="utf-8")
            self.assertIn("lunarnewyear>valentine", action)
            readme = (ROOT / "README.md").read_text(encoding="utf-8")
            self.assertIn("lunarnewyear>valentine", readme)

    def test_cli_auto_palette_follows_injected_date_not_the_clock(self) -> None:
        import json

        payload = _json_calendar(
            "demo",
            date(2026, 10, 11),
            date(2026, 10, 17),
            {date(2026, 10, 12): (4, 2)},
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "calendar.json"
            source.write_text(json.dumps(payload), encoding="utf-8")

            def render(name: str, day: date, flag: str | None) -> tuple[str, str]:
                folder = Path(tmp) / name
                argv = ["--input", str(source), "--out", str(folder), "--seed", "0"]
                if flag is not None:
                    argv.extend(["--palette", flag])
                stderr = io.StringIO()
                with patch("generate.datetime") as clock:
                    clock.now.side_effect = AssertionError("palette selection read the clock")
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                        code = generate.main(argv, today=day)
                self.assertEqual(code, 0, stderr.getvalue())
                return (
                    (folder / "tetris-contrib.svg").read_text(encoding="utf-8"),
                    (folder / "tetris-contrib-dark.svg").read_text(encoding="utf-8"),
                )

            halloween_day = render("oct31", date(2024, 10, 31), "AUTO")
            ordinary_day = render("nov1", date(2026, 11, 1), "auto")
            day_before = render("oct30", date(2028, 10, 30), "auto")
            forced = render("forced", date(2026, 11, 1), "halloween")
            omitted = render("omitted", date(2026, 10, 31), None)
            christmas_eve = render("dec24", date(2024, 12, 24), "auto")
            christmas_day = render("dec25", date(2026, 12, 25), "auto")
            boxing_day = render("dec26", date(2028, 12, 26), "AUTO")
            before_christmas = render("dec23", date(2026, 12, 23), "auto")
            after_christmas = render("dec27", date(2020, 12, 27), "auto")
            forced_christmas = render("forced-christmas", date(2026, 11, 1), "christmas")
            new_years_eve = render("dec31", date(2026, 12, 31), "auto")
            new_years_day = render("jan1", date(2026, 1, 1), "auto")
            day_after_new_year = render("jan2", date(2024, 1, 2), "AUTO")
            forced_newyear = render("forced-newyear", date(2026, 12, 31), "newyear")
            lunar_day = render("lunar-day", date(2026, 2, 17), "auto")
            lunar_last = render("lunar-last", date(2026, 2, 19), "AUTO")
            before_lunar = render("lunar-before", date(2026, 2, 16), "auto")
            after_lunar = render("lunar-after", date(2026, 2, 20), "auto")
            lunar_february = render("lunar-feb", date(2033, 2, 1), "auto")
            outside_table = render("lunar-2025", date(2025, 2, 17), "auto")
            january_in_table_year = render("lunar-jan1", date(2031, 1, 1), "auto")
            forced_lunar = render("forced-lunar", date(2026, 11, 1), "lunarnewyear")
            valentine_day = render("feb14", date(2026, 2, 14), "auto")
            valentine_leap = render("feb14-2024", date(2024, 2, 14), "AUTO")
            valentine_2029 = render("feb14-2029", date(2029, 2, 14), "auto")
            before_valentine = render("feb13-2026", date(2026, 2, 13), "auto")
            after_valentine = render("feb15-2026", date(2026, 2, 15), "auto")
            lunar_2029_before = render("feb13-2029", date(2029, 2, 13), "auto")
            lunar_2029_after = render("feb15-2029", date(2029, 2, 15), "auto")
            forced_valentine = render("forced-valentine", date(2026, 11, 1), "valentine")

            def is_halloween(pair: tuple[str, str]) -> bool:
                light, dark = pair
                return 'fill="#f0db3d"' in light and 'fill="#fac68f"' in dark

            def is_green(pair: tuple[str, str]) -> bool:
                light, dark = pair
                return 'fill="#aceebb"' in light and 'fill="#56d364"' in dark

            def is_christmas(pair: tuple[str, str]) -> bool:
                light, dark = pair
                return 'fill="#a7c957"' in light and 'fill="#bc4749"' in dark

            def is_newyear(pair: tuple[str, str]) -> bool:
                light, dark = pair
                return 'fill="#f9e6a8"' in light and 'fill="#4d2a00"' in dark and 'fill="#f2a900"' in light

            def is_lunar(pair: tuple[str, str]) -> bool:
                light, dark = pair
                return 'fill="#ebc862"' in light and 'fill="#830010"' in dark and 'fill="#c50100"' in light

            def is_valentine(pair: tuple[str, str]) -> bool:
                light, dark = pair
                return 'fill="#f7aee8"' in light and 'fill="#d81a37"' in dark and 'fill="#fd647c"' in light

            self.assertTrue(is_halloween(halloween_day))
            self.assertTrue(is_green(ordinary_day))
            self.assertTrue(is_green(day_before))
            self.assertEqual(ordinary_day, day_before)
            self.assertTrue(is_halloween(forced))
            self.assertEqual(forced[0], halloween_day[0])
            self.assertEqual(forced[1], halloween_day[1])
            self.assertTrue(is_green(omitted))
            self.assertEqual(omitted, ordinary_day)
            self.assertTrue(is_christmas(christmas_eve))
            self.assertTrue(is_christmas(christmas_day))
            self.assertTrue(is_christmas(boxing_day))
            self.assertEqual(christmas_eve, christmas_day)
            self.assertEqual(christmas_day, boxing_day)
            self.assertEqual(forced_christmas, christmas_day)
            self.assertTrue(is_green(before_christmas))
            self.assertTrue(is_green(after_christmas))
            self.assertEqual(before_christmas, ordinary_day)
            self.assertEqual(after_christmas, ordinary_day)
            self.assertNotEqual(christmas_day, halloween_day)
            self.assertTrue(is_green(new_years_eve))
            self.assertFalse(is_christmas(new_years_eve))
            self.assertFalse(is_newyear(new_years_eve))
            self.assertEqual(new_years_eve, ordinary_day)
            self.assertTrue(is_newyear(new_years_day))
            self.assertFalse(is_green(new_years_day))
            self.assertFalse(is_christmas(new_years_day))
            self.assertTrue(is_green(day_after_new_year))
            self.assertEqual(day_after_new_year, ordinary_day)
            self.assertTrue(is_newyear(forced_newyear))
            self.assertEqual(forced_newyear, new_years_day)
            self.assertNotEqual(new_years_day, christmas_day)
            self.assertTrue(is_lunar(lunar_day))
            self.assertTrue(is_lunar(lunar_last))
            self.assertTrue(is_lunar(lunar_february))
            self.assertEqual(lunar_day, lunar_last)
            self.assertEqual(lunar_last, lunar_february)
            self.assertEqual(forced_lunar, lunar_day)
            self.assertTrue(is_green(before_lunar))
            self.assertTrue(is_green(after_lunar))
            self.assertTrue(is_green(outside_table))
            self.assertEqual(before_lunar, ordinary_day)
            self.assertEqual(after_lunar, ordinary_day)
            self.assertEqual(outside_table, ordinary_day)
            self.assertTrue(is_newyear(january_in_table_year))
            self.assertFalse(is_lunar(january_in_table_year))
            self.assertFalse(is_lunar(new_years_day))
            self.assertFalse(is_newyear(lunar_day))
            self.assertFalse(is_christmas(lunar_day))
            self.assertTrue(is_valentine(valentine_day))
            self.assertTrue(is_valentine(valentine_leap))
            self.assertEqual(valentine_day, valentine_leap)
            self.assertEqual(forced_valentine, valentine_day)
            self.assertTrue(is_green(before_valentine))
            self.assertTrue(is_green(after_valentine))
            self.assertEqual(before_valentine, ordinary_day)
            self.assertEqual(after_valentine, ordinary_day)
            self.assertTrue(is_lunar(lunar_2029_before))
            self.assertTrue(is_lunar(lunar_2029_after))
            self.assertEqual(lunar_2029_before, lunar_day)
            self.assertFalse(is_valentine(lunar_2029_before))
            self.assertFalse(is_valentine(lunar_2029_after))
            self.assertFalse(is_valentine(lunar_day))
            self.assertFalse(is_green(valentine_day))
            self.assertFalse(is_newyear(valentine_day))
            self.assertFalse(is_christmas(valentine_day))
            self.assertNotEqual(valentine_day, lunar_day)
            # 14 February 2029 is a dual-festival fade, not plain valentine.
            fade_light, fade_dark = valentine_2029
            self.assertIn("tone-start", fade_light)
            self.assertIn("tone-end", fade_light)
            self.assertIn("@keyframes tone-start", fade_light)
            self.assertIn('fill="#ebc862"', fade_light)
            self.assertIn('fill="#f7aee8"', fade_light)
            self.assertIn('fill="#830010"', fade_dark)
            self.assertIn('fill="#d81a37"', fade_dark)
            self.assertNotEqual(valentine_2029, valentine_day)
            self.assertNotEqual(valentine_2029, lunar_day)
            self.assertFalse(is_green(valentine_2029))
            # Non-overlap 14 February has no fade and no Lunar New Year colors.
            self.assertNotIn("tone-start", valentine_day[0])
            self.assertNotIn("#ebc862", valentine_day[0])

    def test_cli_rejects_unknown_palette_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            light = Path(tmp) / "light.svg"
            dark = Path(tmp) / "dark.svg"
            missing = Path(tmp) / "missing.json"
            env = os.environ.copy()
            for bad in ("", "green", "seasonal", "winter"):
                proc = _run_generate(
                    [
                        "--input",
                        str(missing),
                        "--light",
                        str(light),
                        "--dark",
                        str(dark),
                        "--palette",
                        bad,
                    ],
                    env=env,
                )
                self.assertNotEqual(proc.returncode, 0, bad)
                self.assertIn("palette", proc.stderr)
                self.assertIn("halloween", proc.stderr)
                self.assertIn("christmas", proc.stderr)
                self.assertIn("newyear", proc.stderr)
                self.assertIn("valentine", proc.stderr)
                self.assertIn("lunarnewyear", proc.stderr)
                self.assertIn("31 October", proc.stderr)
                self.assertIn("24-26 December", proc.stderr)
                self.assertIn("1 January", proc.stderr)
                self.assertIn("14 February", proc.stderr)
                self.assertIn("17-19 February 2026", proc.stderr)
                self.assertIn("lunarnewyear>valentine", proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)
                self.assertNotIn("was not found", proc.stderr)
                self.assertFalse(light.exists())
                self.assertFalse(dark.exists())
                self.assertFalse(missing.exists())


def _fall_frames(svg: str) -> str:
    start = svg.index("@keyframes fall{") + len("@keyframes fall{")
    return svg[start : svg.index("}@keyframes lock", start)]


def _brick_refs(svg: str) -> list[str]:
    needle = 'href="#'
    refs: list[str] = []
    start = 0
    while True:
        found = svg.find(needle, start)
        if found == -1:
            return refs
        end = svg.index('"', found + len(needle))
        refs.append(svg[found + len(needle) : end])
        start = end


def _animation_clock(svg: str) -> tuple[float, list[float]]:
    marker = "animation:fall "
    start = svg.index(marker) + len(marker)
    duration = float(svg[start : svg.index("s ", start)])
    needle = "animation-delay:"
    delays: list[float] = []
    cursor = 0
    while True:
        found = svg.find(needle, cursor)
        if found == -1:
            return duration, delays
        found += len(needle)
        end = svg.index("s", found)
        delays.append(float(svg[found:end]))
        cursor = end


def _run_generate(args: list[str], *, env: dict[str, str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "generate.py"), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def _api_calendar(day: str, count: int, level: str) -> dict:
    """One contribution day in the shape ``fetch_calendar`` reads from GraphQL."""
    return {
        "user": {
            "contributionsCollection": {
                "contributionCalendar": {
                    "weeks": [
                        {
                            "contributionDays": [
                                {
                                    "date": day,
                                    "contributionCount": count,
                                    "contributionLevel": level,
                                }
                            ]
                        }
                    ]
                }
            }
        }
    }


def _json_calendar(
    username: str,
    start: date,
    end: date,
    counts: dict[date, tuple[int, int]] | None = None,
) -> dict:
    """Days from ``start`` through ``end``, split on Sunday.

    The first and last groups stay short when the range does not open on
    Sunday or close on Saturday. That is the shape a partial week arrives in.
    """
    counts = counts or {}
    level_names = ("NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE")
    weeks: list[list[dict]] = []
    column: list[dict] = []
    day = start
    while day <= end:
        if column and (day.weekday() + 1) % 7 == 0:
            weeks.append(column)
            column = []
        count, level = counts.get(day, (0, 0))
        column.append(
            {
                "date": day.isoformat(),
                "contributionCount": count,
                "contributionLevel": level_names[level],
            }
        )
        day += timedelta(days=1)
    if column:
        weeks.append(column)
    return {
        "username": username,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "weeks": weeks,
    }


def _tiny_calendar() -> Calendar:
    start = date(2026, 10, 11)
    weeks = []
    total_days = 0
    for col in range(2):
        column = []
        for row in range(7):
            count = 1 if (col, row) == (0, 0) else 0
            level = 1 if count else 0
            column.append(Day(start.fromordinal(start.toordinal() + total_days), count, level))
            total_days += 1
        weeks.append(tuple(column))
    return Calendar("tester", start, weeks[-1][-1].date, tuple(weeks))


if __name__ == "__main__":
    unittest.main()
