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
    parse_seed,
    parse_speed,
    validate_output_path,
)
from brickfall import (  # noqa: E402
    ORIENTATIONS,
    SMALL_PIECES,
    TETROMINOES,
    Calendar,
    CalendarParseError,
    Day,
    GraphQLError,
    _graphql,
    calendar_from_json,
    calendar_to_json,
    coverage_errors,
    decompose,
    fetch_calendar,
    lands_before,
    make_timeline,
    match_shape,
    pieces_for_calendar,
    profile_window,
    render_svg,
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

    def test_action_style_inputs_still_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["TETRIS_REQUIRE_RELATIVE"] = "1"
            proc = _run_generate(
                [
                    "--input",
                    str(SAMPLE),
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
            light = Path(tmp) / "dist" / "tetris-contrib.svg"
            dark = Path(tmp) / "dist" / "tetris-contrib-dark.svg"
            self.assertIn("#aceebb", light.read_text(encoding="utf-8"))
            self.assertIn("#56d364", dark.read_text(encoding="utf-8"))
            self.assertIn("KenYanL", light.read_text(encoding="utf-8"))

            absolute = _run_generate(
                [
                    "--input",
                    str(SAMPLE),
                    "--light",
                    str(Path(tmp) / "abs.svg"),
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
            self.assertFalse((Path(tmp) / "abs.svg").exists())

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

            directory_run = _run_generate(
                ["--input", str(root), "--out", str(out)],
                env=env,
            )
            self.assertEqual(directory_run.returncode, 1)
            self.assertIn("is a directory", directory_run.stderr)
            self.assertIn("sample/contributions.json", directory_run.stderr)
            self.assertNotIn("Traceback", directory_run.stderr)
            self.assertFalse(out.exists())

            binary = root / "calendar.bin"
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
