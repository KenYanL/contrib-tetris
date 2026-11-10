"""Build a looping Tetris/LEGO SVG from a GitHub contribution calendar.

The calendar is the same 7-by-weeks grid shown on a GitHub profile. Every cell
is packed into a standard tetromino (I, O, T, S, Z, L, J), using rotations.
Cells that cannot join one become trominoes, dominoes, or single bricks. Each
piece falls from above the grid and locks on the day it belongs to, so the
last frame is the real contribution graph.

This module is original. It does not wrap or copy the snake action or the
other contribution-graph animations listed in README.md.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Iterator, Sequence


# Live github.com Primer tokens (contribution.default), captured 2026-10-17.
PALETTES: dict[str, dict[str, object]] = {
    "light": {
        "levels": ("#eff2f5", "#aceebb", "#4ac26b", "#2da44e", "#116329"),
        "text": "#59636e",
        "border": "rgba(31,35,40,0.06)",
    },
    "dark": {
        "levels": ("#151b23", "#033a16", "#196c2e", "#2ea043", "#56d364"),
        "text": "#9198a1",
        "border": "rgba(240,246,252,0.05)",
    },
}

# --contribution-halloween-bgColor-1..4 from @primer/primitives 11.10.0
# (dist/css/functional/themes/light.css and dark.css). Level 0 keeps
# --contribution-default-bgColor-0: Primer's Halloween tokens start at level 1.
# Text and the cell border match the default theme.
HALLOWEEN_PALETTES: dict[str, dict[str, object]] = {
    "light": {
        "levels": ("#eff2f5", "#f0db3d", "#ffd642", "#f68c41", "#1f2328"),
        "text": "#59636e",
        "border": "rgba(31,35,40,0.06)",
    },
    "dark": {
        "levels": ("#151b23", "#fac68f", "#c46212", "#984b10", "#e3d04f"),
        "text": "#9198a1",
        "border": "rgba(240,246,252,0.05)",
    },
}

# Coolors' most popular Christmas palette
# (https://coolors.co/palettes/popular/christmas):
# 386641, 6a994e, a7c957, f2e8cf, bc4749.
# The cream (#f2e8cf) is dropped. Level 0 keeps the neutral GitHub empty
# cell. The other four colors are ordered by contrast against that
# background. Text and the cell border match the default theme.
# Light: #eff2f5 #a7c957 #6a994e #bc4749 #386641
# Dark:  #151b23 #386641 #bc4749 #6a994e #a7c957
CHRISTMAS_PALETTES: dict[str, dict[str, object]] = {
    "light": {
        "levels": ("#eff2f5", "#a7c957", "#6a994e", "#bc4749", "#386641"),
        "text": "#59636e",
        "border": "rgba(31,35,40,0.06)",
    },
    "dark": {
        "levels": ("#151b23", "#386641", "#bc4749", "#6a994e", "#a7c957"),
        "text": "#9198a1",
        "border": "rgba(240,246,252,0.05)",
    },
}

# Color Hunt gold gradient palette
# (https://colorhunt.co/palette/f9e6a8f2a900cc6f004d2a00):
# f9e6a8, f2a900, cc6f00, 4d2a00.
# Level 0 keeps the neutral GitHub empty cell. The other four colors
# are ordered by contrast against that background. Text and the cell
# border match the default theme.
# Light: #eff2f5 #f9e6a8 #f2a900 #cc6f00 #4d2a00
# Dark:  #151b23 #4d2a00 #cc6f00 #f2a900 #f9e6a8
NEWYEAR_PALETTES: dict[str, dict[str, object]] = {
    "light": {
        "levels": ("#eff2f5", "#f9e6a8", "#f2a900", "#cc6f00", "#4d2a00"),
        "text": "#59636e",
        "border": "rgba(31,35,40,0.06)",
    },
    "dark": {
        "levels": ("#151b23", "#4d2a00", "#cc6f00", "#f2a900", "#f9e6a8"),
        "text": "#9198a1",
        "border": "rgba(240,246,252,0.05)",
    },
}

# SchemeColor's Chinese Gold & Red
# (https://www.schemecolor.com/chinese-gold-red.php):
# 960316, ebc862, e4b034, ca9d08, c50100, 830010.
# Scarlett (#960316) and Chinese Gold (#ca9d08) are dropped as
# near-duplicates. Level 0 keeps the neutral GitHub empty cell. The
# other four colors run from lightest to darkest on the light graph
# and the reverse on the dark graph. Text and the cell border match
# the default theme.
# Light: #eff2f5 #ebc862 #e4b034 #c50100 #830010
# Dark:  #151b23 #830010 #c50100 #e4b034 #ebc862
LUNAR_NEW_YEAR_PALETTES: dict[str, dict[str, object]] = {
    "light": {
        "levels": ("#eff2f5", "#ebc862", "#e4b034", "#c50100", "#830010"),
        "text": "#59636e",
        "border": "rgba(31,35,40,0.06)",
    },
    "dark": {
        "levels": ("#151b23", "#830010", "#c50100", "#e4b034", "#ebc862"),
        "text": "#9198a1",
        "border": "rgba(240,246,252,0.05)",
    },
}

# SchemeColor's Valentine's Hearts
# (https://www.schemecolor.com/valentines-hearts.php):
# f7aee8, fd647c, f6383a, d81a37.
# All four source colors are used exactly. Level 0 keeps the neutral
# GitHub empty cell. The four colors run from lightest to darkest on
# the light graph and the reverse on the dark graph. Text and the
# cell border match the default theme.
# Light: #eff2f5 #f7aee8 #fd647c #f6383a #d81a37
# Dark:  #151b23 #d81a37 #f6383a #fd647c #f7aee8
VALENTINE_PALETTES: dict[str, dict[str, object]] = {
    "light": {
        "levels": ("#eff2f5", "#f7aee8", "#fd647c", "#f6383a", "#d81a37"),
        "text": "#59636e",
        "border": "rgba(31,35,40,0.06)",
    },
    "dark": {
        "levels": ("#151b23", "#d81a37", "#f6383a", "#fd647c", "#f7aee8"),
        "text": "#9198a1",
        "border": "rgba(240,246,252,0.05)",
    },
}

# First day of Lunar New Year (春节) as a UTC calendar date.
# These are the first day of the first lunar month in the Hong Kong
# Observatory Gregorian-Lunar conversion tables
# (https://www.hko.gov.hk/en/gts/time/conversion.htm). The same days are
# listed for Chinese New Year by
# https://en.wikipedia.org/wiki/Chinese_New_Year and
# https://www.timeanddate.com/holidays/china/spring-festival.
# ``auto`` does not shift them for China Standard Time: the UTC calendar
# day equal to this Gregorian date is the festival day. A year that is
# not in the table is never lunarnewyear.
LUNAR_NEW_YEAR_DATES: tuple[date, ...] = (
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
)
# Christmas covers three UTC days (24-26 December). Lunar New Year uses
# that same length: the tabulated day and the two UTC days after it.
# The earliest tabulated day is 23 January, so the window never includes
# 1 January and does not overlap ``newyear``. If a day in the window is
# also a Western holiday, such as 14 February 2029 (Valentine's Day),
# ``auto`` still lists both dates and fades from this palette to the
# Western one.
LUNAR_NEW_YEAR_SPAN_DAYS = 3
VALENTINE_DAY = (2, 14)

@dataclass(frozen=True)
class PaletteTransition:
    """A color fade from one concrete palette to another.

    ``auto`` returns this when a Chinese traditional festival and a
    Western holiday share a UTC day. The graph starts in ``start`` and
    fades into ``end``. The CLI form is ``start>end``, for example
    ``lunarnewyear>valentine``.
    """

    start: str
    end: str

    def __str__(self) -> str:
        return f"{self.start}>{self.end}"


@dataclass(frozen=True)
class PaletteSpec:
    """One concrete palette: both themes, a short error-text phrase, and UTC days.

    ``summary`` finishes "use <name> for <summary>" when a palette name is
    rejected. ``auto_days`` is the UTC (month, day) pairs ``auto`` paints with
    this palette every year. ``auto_dates`` is the UTC calendar dates it
    paints in particular years, for a holiday that moves. Empty means
    ``auto`` never selects that field. ``tradition`` is ``chinese`` for a
    Chinese traditional festival, ``western`` for a Western holiday, or
    ``none`` for the default green graph. When a Chinese date and a
    Western date coincide, ``auto`` fades from the Chinese palette to
    the Western one.
    """

    themes: dict[str, dict[str, object]]
    summary: str
    auto_days: tuple[tuple[int, int], ...] = ()
    auto_dates: tuple[date, ...] = ()
    tradition: str = "western"


def _holiday_window(
    anchors: tuple[date, ...],
    days: int,
    skip: tuple[tuple[int, int], ...] = (),
) -> tuple[date, ...]:
    """Each anchor date plus the following UTC days, ``days`` long in all.

    ``days`` includes the anchor. A span of 3 is the anchor and the next
    two UTC days, the same length as 24-26 December. ``skip`` is UTC
    (month, day) pairs left out of the window, so a moving holiday does
    not take a day that already belongs to a repeating palette.
    """
    if days < 1:
        raise ValueError("a holiday window covers at least one day")
    excluded = set(skip)
    return tuple(
        day
        for anchor in anchors
        for offset in range(days)
        for day in (anchor + timedelta(days=offset),)
        if (day.month, day.day) not in excluded
    )


# Concrete palettes in the order ``auto`` checks them. ``default`` is first
# and is the fallback, so it lists no days. To add a holiday, append one
# entry with its light and dark scales, the phrase for the error text, and
# either the UTC month-days it covers every year or the UTC dates for a
# holiday that moves. A Chinese festival and a Western holiday may share
# a calendar day; ``auto`` then fades from the Chinese palette to the
# Western one. Two holidays of the same tradition cannot share a day.
PALETTE_CATALOG: tuple[tuple[str, PaletteSpec], ...] = (
    ("default", PaletteSpec(PALETTES, "the usual green graph", tradition="none")),
    (
        "halloween",
        PaletteSpec(HALLOWEEN_PALETTES, "GitHub's Halloween colors", ((10, 31),)),
    ),
    (
        "christmas",
        PaletteSpec(
            CHRISTMAS_PALETTES,
            "Coolors' popular Christmas palette",
            ((12, 24), (12, 25), (12, 26)),
        ),
    ),
    (
        "newyear",
        PaletteSpec(
            NEWYEAR_PALETTES,
            "Color Hunt's New Year gold palette",
            ((1, 1),),
        ),
    ),
    (
        "valentine",
        PaletteSpec(
            VALENTINE_PALETTES,
            "SchemeColor's Valentine's Hearts palette",
            (VALENTINE_DAY,),
        ),
    ),
    (
        "lunarnewyear",
        PaletteSpec(
            LUNAR_NEW_YEAR_PALETTES,
            "SchemeColor's Chinese gold and red palette",
            auto_dates=_holiday_window(LUNAR_NEW_YEAR_DATES, LUNAR_NEW_YEAR_SPAN_DAYS),
            tradition="chinese",
        ),
    ),
)


def _fade_or_conflict(left: str, right: str, traditions: dict[str, str], label: str) -> PaletteTransition:
    """Return a Chinese-to-Western fade, or reject two holidays of the same tradition."""
    chinese = [name for name in (left, right) if traditions[name] == "chinese"]
    western = [name for name in (left, right) if traditions[name] == "western"]
    if len(set((left, right))) == 2 and len(chinese) == 1 and len(western) == 1:
        return PaletteTransition(chinese[0], western[0])
    raise ValueError(
        f"auto date {label} is listed for {left!r} and {right!r}. "
        "Each calendar day belongs to one palette, unless a Chinese "
        "traditional festival and a Western holiday share it."
    )


def _validate_palette_catalog(
    catalog: tuple[tuple[str, PaletteSpec], ...],
) -> tuple[dict[tuple[int, int], PaletteTransition], dict[date, PaletteTransition]]:
    """Reject a catalog ``auto`` could not apply, before any SVG is drawn.

    Every concrete palette keeps level 0 as the neutral empty-cell color
    from the default graph. A Chinese festival and a Western holiday may
    share a UTC day; that pair becomes a color fade. Any other overlap
    is rejected.
    """
    if (
        not catalog
        or catalog[0][0] != "default"
        or catalog[0][1].auto_days
        or catalog[0][1].auto_dates
        or catalog[0][1].tradition != "none"
    ):
        raise ValueError(
            "the palette catalog must start with default, and default cannot list auto days "
            "or auto dates. default is the fallback for every other UTC day."
        )
    seen_names: set[str] = set()
    seen_days: dict[tuple[int, int], str] = {}
    seen_dates: dict[date, str] = {}
    traditions: dict[str, str] = {}
    day_fades: dict[tuple[int, int], PaletteTransition] = {}
    date_fades: dict[date, PaletteTransition] = {}
    # Level 0 of the default graph. Holidays may recolor active cells only.
    neutral_level0: dict[str, object] = {}
    for name, spec in catalog:
        if not isinstance(name, str) or name.strip() == "" or name != name.strip():
            raise ValueError(f"palette name {name!r} cannot be registered. Use a short name such as halloween.")
        if name == "auto":
            raise ValueError(
                "palette name 'auto' is the date selector, not a concrete palette. "
                "List the holiday under its own name and put its UTC days in auto_days."
            )
        if name in seen_names:
            raise ValueError(f"palette name {name!r} is listed more than once.")
        seen_names.add(name)
        if spec.tradition not in {"none", "western", "chinese"}:
            raise ValueError(
                f"palette {name!r} tradition is {spec.tradition!r}. "
                "Use 'chinese', 'western', or 'none'."
            )
        if name == "default" and spec.tradition != "none":
            raise ValueError("the default palette tradition must be 'none'.")
        if name != "default" and spec.tradition == "none":
            raise ValueError(f"palette {name!r} cannot use tradition 'none'. That is reserved for default.")
        traditions[name] = spec.tradition
        if not isinstance(spec.summary, str) or spec.summary.strip() == "":
            raise ValueError(f"palette {name!r} needs a short summary for the error text.")
        if set(spec.themes) != {"light", "dark"}:
            raise ValueError(f"palette {name!r} needs a light theme and a dark theme.")
        for theme, colors in spec.themes.items():
            levels = colors.get("levels")
            if not isinstance(levels, tuple) or len(levels) != 5:
                raise ValueError(f"palette {name!r} {theme} needs five level colors.")
            if name == "default":
                neutral_level0[theme] = levels[0]
            elif levels[0] != neutral_level0[theme]:
                raise ValueError(
                    f"palette {name!r} {theme} level 0 is {levels[0]!r}, "
                    f"but every palette keeps the neutral empty-cell color {neutral_level0[theme]!r} "
                    "from the default graph."
                )
            if "text" not in colors or "border" not in colors:
                raise ValueError(f"palette {name!r} {theme} needs text and border colors.")
        for month, day in spec.auto_days:
            try:
                # 2024 is a leap year, so 29 February is a real auto day.
                date(2024, month, day)
            except ValueError:
                raise ValueError(
                    f"palette {name!r} lists auto date {(month, day)!r}, which is not a calendar day. "
                    "Use a real month and day, such as (10, 31)."
                ) from None
            previous = seen_days.get((month, day))
            if previous is not None:
                day_fades[(month, day)] = _fade_or_conflict(
                    previous, name, traditions, repr((month, day))
                )
            for when, owner in list(seen_dates.items()):
                if (when.month, when.day) == (month, day) and owner != name:
                    date_fades[when] = _fade_or_conflict(
                        owner, name, traditions, when.isoformat()
                    )
            seen_days[(month, day)] = name
        for when in spec.auto_dates:
            if type(when) is not date:
                raise ValueError(
                    f"palette {name!r} lists auto date {when!r}, which is not a calendar date. "
                    "Use a datetime.date, such as date(2026, 2, 17)."
                )
            previous_date = seen_dates.get(when)
            if previous_date is not None:
                date_fades[when] = _fade_or_conflict(
                    previous_date, name, traditions, when.isoformat()
                )
            owner = seen_days.get((when.month, when.day))
            if owner is not None and owner != name:
                date_fades[when] = _fade_or_conflict(
                    owner, name, traditions, when.isoformat()
                )
            seen_dates[when] = name
    return day_fades, date_fades


AUTO_TRANSITIONS_DAYS, AUTO_TRANSITIONS_DATES = _validate_palette_catalog(PALETTE_CATALOG)

# Concrete palettes render_svg can paint. ``auto`` is resolved before this.
PALETTE_TABLES: dict[str, dict[str, dict[str, object]]] = {
    name: spec.themes for name, spec in PALETTE_CATALOG
}
PALETTE_NAMES = tuple(name for name, _spec in PALETTE_CATALOG) + ("auto",)
# Dated rows of the catalog, in the same order ``auto`` checks them.
# The third item is empty for a holiday that repeats every year.
AUTO_HOLIDAYS: tuple[tuple[str, tuple[tuple[int, int], ...], tuple[date, ...]], ...] = tuple(
    (name, spec.auto_days, spec.auto_dates)
    for name, spec in PALETTE_CATALOG
    if spec.auto_days or spec.auto_dates
)

_MONTHS = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _join_phrases(parts: Sequence[str]) -> str:
    """Join holiday phrases the way the error text lists them."""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


def format_auto_days(days: Sequence[tuple[int, int]]) -> str:
    """Collapse UTC month-days into a phrase such as ``31 October`` or ``24-26 December``.

    Consecutive days in one month become a range. Separate runs are joined
    with ``and``.
    """
    if not days:
        raise ValueError("auto days are empty")
    groups: list[tuple[int, int, int]] = []
    for month, day in sorted(days):
        if groups and groups[-1][0] == month and groups[-1][2] + 1 == day:
            groups[-1] = (month, groups[-1][1], day)
        else:
            groups.append((month, day, day))
    parts: list[str] = []
    for month, start, end in groups:
        name = _MONTHS[month]
        if start == end:
            parts.append(f"{start} {name}")
        else:
            parts.append(f"{start}-{end} {name}")
    return _join_phrases(parts)


def format_auto_dates(dates: Sequence[date]) -> str:
    """Collapse UTC dates into a phrase such as ``17-19 February 2026``.

    Consecutive days become one range. A range that stays in one month is
    ``17-19 February 2026``. A range that crosses a month is
    ``31 January-2 February 2033``. Separate runs are joined with ``and``.
    """
    if not dates:
        raise ValueError("auto dates are empty")
    ordered = sorted(dates)
    runs: list[tuple[date, date]] = []
    for when in ordered:
        if runs and runs[-1][1] + timedelta(days=1) == when:
            runs[-1] = (runs[-1][0], when)
        else:
            runs.append((when, when))
    parts: list[str] = []
    for start, end in runs:
        if start == end:
            parts.append(f"{start.day} {_MONTHS[start.month]} {start.year}")
        elif start.month == end.month and start.year == end.year:
            parts.append(f"{start.day}-{end.day} {_MONTHS[start.month]} {start.year}")
        elif start.year == end.year:
            parts.append(
                f"{start.day} {_MONTHS[start.month]}-{end.day} {_MONTHS[end.month]} {end.year}"
            )
        else:
            parts.append(
                f"{start.day} {_MONTHS[start.month]} {start.year}"
                f"-{end.day} {_MONTHS[end.month]} {end.year}"
            )
    return _join_phrases(parts)


def _fade_help() -> str:
    """Sentence describing Chinese-to-Western fades, or empty if none exist."""
    if not AUTO_TRANSITIONS_DAYS and not AUTO_TRANSITIONS_DATES:
        return ""
    return (
        " When a Chinese traditional festival and a Western holiday share a UTC day, "
        "auto starts on the Chinese palette and fades into the Western palette. "
        "A value such as lunarnewyear>valentine paints that fade on any day."
    )


def palette_hint() -> str:
    """Sentence appended when a palette name is rejected.

    Built from ``PALETTE_CATALOG``, so a new holiday shows up in the error
    without a second copy of its dates.
    """
    named = ", ".join(f"{name} for {spec.summary}" for name, spec in PALETTE_CATALOG)
    auto_parts: list[str] = []
    for name, spec in PALETTE_CATALOG:
        if spec.auto_days:
            auto_parts.append(f"{name} on {format_auto_days(spec.auto_days)} (UTC)")
        if spec.auto_dates:
            auto_parts.append(f"{name} on {format_auto_dates(spec.auto_dates)} (UTC)")
    return (
        f"Use {named}, or auto to use {', '.join(auto_parts)}, and default every other day."
        + _fade_help()
    )


def palette_cli_help() -> str:
    """Argparse help for ``--palette``, built from ``PALETTE_CATALOG``.

    A new holiday shows up in ``--help`` without a second copy of its dates
    or summary. Year-specific ``auto_dates`` also state that a year outside
    the table stays on default.
    """
    parts: list[str] = ["Contribution colors for both the light and dark SVGs."]
    for name, spec in PALETTE_CATALOG:
        if name == "default":
            parts.append(f"{name} is {spec.summary}.")
        else:
            parts.append(f"{name} uses {spec.summary}.")
    auto_parts: list[str] = []
    outside_parts: list[str] = []
    for name, spec in PALETTE_CATALOG:
        if spec.auto_days:
            auto_parts.append(f"{name} on {format_auto_days(spec.auto_days)} (UTC)")
        if spec.auto_dates:
            auto_parts.append(f"{name} on {format_auto_dates(spec.auto_dates)} (UTC)")
            years = [when.year for when in spec.auto_dates]
            outside_parts.append(
                f"A year outside {min(years)}-{max(years)} stays on default for {name}"
            )
    if auto_parts:
        parts.append(
            f"auto uses {', '.join(auto_parts)}, and default every other day."
        )
    else:
        parts.append("auto uses default every day.")
    fade = _fade_help().strip()
    if fade:
        parts.append(fade)
    parts.extend(f"{sentence}." for sentence in outside_parts)
    return " ".join(parts)


LEVEL_NAMES = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}


def resolve_palette(name: str, today: date) -> str | PaletteTransition:
    """Return the concrete palette, or a fade, for ``name`` on ``today``.

    ``default``, ``halloween``, ``christmas``, ``newyear``,
    ``valentine``, and ``lunarnewyear`` are returned as given. A name
    such as ``lunarnewyear>valentine`` becomes a ``PaletteTransition``.
    ``auto`` follows ``PALETTE_CATALOG``: halloween on 31 October,
    christmas on 24-26 December, newyear on 1 January, valentine on 14
    February, and lunarnewyear on each tabulated Lunar New Year date
    plus the next two UTC days (2026-2035). When a Chinese traditional
    festival and a Western holiday share a UTC day, ``auto`` fades from
    the Chinese palette to the Western one (14 February 2029 is
    lunarnewyear fading into valentine). 1 January stays newyear.
    Every other day is ``default``, including 31 December, 2 January,
    and a Lunar New Year in a year the table does not list. ``today`` is
    the calendar day to test. This does not read the clock; pass the
    current UTC date when the caller means now.
    """
    if ">" in name:
        start, end = name.split(">", 1)
        if start in PALETTE_TABLES and end in PALETTE_TABLES and start != end:
            return PaletteTransition(start, end)
        raise ValueError(f"unknown palette {name!r}")
    if name == "auto":
        key = (today.month, today.day)
        if today in AUTO_TRANSITIONS_DATES:
            return AUTO_TRANSITIONS_DATES[today]
        if key in AUTO_TRANSITIONS_DAYS:
            return AUTO_TRANSITIONS_DAYS[key]
        for palette, days, dates in AUTO_HOLIDAYS:
            if key in days or today in dates:
                return palette
        return "default"
    if name not in PALETTE_TABLES:
        raise ValueError(f"unknown palette {name!r}")
    return name

CELL = 11
GAP = 3
STEP = CELL + GAP
ROWS = 7

# Canonical orientations before rotation. (row, col), row grows downward.
TETROMINOES: dict[str, tuple[tuple[int, int], ...]] = {
    "I": ((0, 0), (0, 1), (0, 2), (0, 3)),
    "O": ((0, 0), (0, 1), (1, 0), (1, 1)),
    "T": ((0, 0), (0, 1), (0, 2), (1, 1)),
    "S": ((0, 1), (0, 2), (1, 0), (1, 1)),
    "Z": ((0, 0), (0, 1), (1, 1), (1, 2)),
    "J": ((0, 0), (1, 0), (2, 0), (2, 1)),
    "L": ((0, 1), (1, 1), (2, 0), (2, 1)),
}
SMALL_PIECES: dict[str, tuple[tuple[int, int], ...]] = {
    "I3": ((0, 0), (0, 1), (0, 2)),
    "L3": ((0, 0), (1, 0), (1, 1)),
    "I2": ((0, 0), (0, 1)),
    "I1": ((0, 0),),
}

WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
LABELED_ROWS = {1: "Mon", 3: "Wed", 5: "Fri"}

QUERY = """
query($login:String!,$from:DateTime!,$to:DateTime!){
  user(login:$login){
    contributionsCollection(from:$from,to:$to){
      contributionCalendar{
        totalContributions
        weeks{
          contributionDays{ date contributionCount contributionLevel }
        }
      }
    }
  }
}
"""

QUERY_DEFAULT = """
query($login:String!){
  user(login:$login){
    contributionsCollection{
      contributionCalendar{
        totalContributions
        weeks{
          contributionDays{ date contributionCount contributionLevel }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class Day:
    date: date
    count: int
    level: int


@dataclass(frozen=True)
class Calendar:
    username: str
    start: date
    end: date
    weeks: tuple[tuple[Day, ...], ...]

    @property
    def columns(self) -> int:
        return len(self.weeks)

    @property
    def total(self) -> int:
        return sum(day.count for week in self.weeks for day in week)

    def level_at(self, row: int, col: int) -> int:
        return self.weeks[col][row].level


@dataclass(frozen=True)
class Piece:
    name: str
    cells: tuple[tuple[int, int], ...]

    @property
    def size(self) -> int:
        return len(self.cells)


@dataclass(frozen=True)
class Timeline:
    delays: tuple[float, ...]
    total: float
    fall: float
    bounce: float
    fade_at: float
    fade: float
    drop: float


def years_ago(day: date, years: int = 1) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def profile_window(today: date) -> tuple[date, date]:
    """Sunday-start weeks covering the profile graph for ``today``.

    GitHub draws the week that contains the calendar date one year ago,
    through the Saturday of the current week. That span is a few days
    longer than one year; see ``range_exceeds_one_year``.
    """
    ago = years_ago(today)
    start = ago - timedelta(days=(ago.weekday() + 1) % 7)
    end = today + timedelta(days=(5 - today.weekday()) % 7)
    return start, end


def range_exceeds_one_year(start: date, end: date) -> bool:
    """Whether ``contributionsCollection(from, to)`` is past GitHub's limit.

    ``from`` is ``start`` at 00:00:00Z and ``to`` is ``end`` at 23:59:59Z.
    A range that reaches the anniversary of ``start`` is already past one
    year, because ``to`` is the end of that day. 29 February clamps to
    28 February, same as ``years_ago``.
    """
    try:
        anniversary = start.replace(year=start.year + 1)
    except ValueError:
        anniversary = start.replace(year=start.year + 1, day=28)
    return end >= anniversary


class CalendarParseError(ValueError):
    """A contribution calendar has a field this renderer cannot draw."""


_LEVEL_HINT = (
    "Use 0, 1, 2, 3, or 4, or NONE, FIRST_QUARTILE, SECOND_QUARTILE, "
    "THIRD_QUARTILE, FOURTH_QUARTILE."
)


def _parse_day_date(raw: dict) -> date:
    if "date" not in raw:
        raise CalendarParseError("a contribution day is missing date. Use an ISO date like 2026-10-12.")
    value = raw["date"]
    if not isinstance(value, str) or value.strip() == "":
        raise CalendarParseError(
            f"a contribution day has date {value!r}, which is not an ISO date. Use a date like 2026-10-12."
        )
    try:
        # GitHub dates are YYYY-MM-DD. A datetime prefix still counts as that day.
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        raise CalendarParseError(
            f"a contribution day has date {value!r}, which is not an ISO date. Use a date like 2026-10-12."
        ) from None


def _parse_count(raw: dict, day: date) -> int:
    if "contributionCount" in raw:
        value: object = raw["contributionCount"]
        label = "contributionCount"
    elif "count" in raw:
        value = raw["count"]
        label = "count"
    else:
        return 0
    original = value
    if isinstance(value, str):
        try:
            value = int(value.strip())
        except ValueError:
            value = original
    # bool is an int subclass; True would otherwise become one contribution.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CalendarParseError(
            f"day {day.isoformat()} has {label} {original!r}, which is not a non-negative integer."
        )
    return value


def _parse_level(raw: dict, day: date) -> int:
    """Read a day level. GitHub's contributionLevel wins over an integer level.

    Only 0 through 4 are drawable. Other values used to write an SVG that
    referenced a missing brick, or, for a negative level, borrowed another
    quartile's color for the joint.
    """
    if "contributionLevel" in raw:
        level: object = raw["contributionLevel"]
        label = "contributionLevel"
    elif "level" in raw:
        level = raw["level"]
        label = "level"
    else:
        return 0
    shown = level
    if isinstance(level, str):
        text = level.strip()
        if text in LEVEL_NAMES:
            return LEVEL_NAMES[text]
        try:
            level = int(text)
        except ValueError:
            level = shown
    if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 4:
        raise CalendarParseError(
            f"day {day.isoformat()} has {label} {shown!r}, which is not a contribution level from 0 to 4. "
            f"{_LEVEL_HINT}"
        )
    return level


def _parse_day(raw: dict) -> Day:
    if not isinstance(raw, dict):
        raise CalendarParseError(
            "each contribution day must be an object with a date, "
            'for example {"date": "2026-10-12", "count": 0, "level": 0}.'
        )
    parsed = _parse_day_date(raw)
    return Day(date=parsed, count=_parse_count(raw, parsed), level=_parse_level(raw, parsed))


def _parse_window_date(payload: dict, key: str) -> date:
    if key not in payload:
        raise CalendarParseError(f"{key} is missing. Use an ISO date like 2026-10-12.")
    value = payload[key]
    if not isinstance(value, str) or value.strip() == "":
        raise CalendarParseError(
            f"{key} is {value!r}, which is not an ISO date. Use a date like 2026-10-12."
        )
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        raise CalendarParseError(
            f"{key} is {value!r}, which is not an ISO date. Use a date like 2026-10-12."
        ) from None


def calendar_from_days(username: str, start: date, end: date, days: Iterable[Day]) -> Calendar:
    if end < start:
        raise ValueError(
            f"end {end.isoformat()} is before start {start.isoformat()}. "
            "Use a window that starts on or before it ends, for example 2026-10-12 through 2026-10-17."
        )
    # A partial first week, and a 366-day leap year, are not Sunday-to-Saturday.
    # Pad so row 0 stays Sunday; missing days are empty contributions.
    start = start - timedelta(days=(start.weekday() + 1) % 7)
    end = end + timedelta(days=(5 - end.weekday()) % 7)
    span = (end - start).days + 1
    if span % 7 != 0 or span < 7:
        raise ValueError(f"window {start.isoformat()}..{end.isoformat()} is not a whole number of weeks.")
    columns = span // 7
    grid: list[list[Day | None]] = [[None] * ROWS for _ in range(columns)]
    for day in days:
        if day.date < start or day.date > end:
            continue
        index = (day.date - start).days
        col, row = divmod(index, 7)
        grid[col][row] = day
    weeks: list[tuple[Day, ...]] = []
    for col in range(columns):
        column: list[Day] = []
        for row in range(ROWS):
            existing = grid[col][row]
            if existing is None:
                existing = Day(start + timedelta(days=col * 7 + row), 0, 0)
            column.append(existing)
        weeks.append(tuple(column))
    return Calendar(username=username, start=start, end=end, weeks=tuple(weeks))


def calendar_from_json(payload: object) -> Calendar:
    if not isinstance(payload, dict):
        raise CalendarParseError("the calendar must be a JSON object with start, end, and weeks.")
    start = _parse_window_date(payload, "start")
    end = _parse_window_date(payload, "end")
    if "weeks" not in payload:
        raise CalendarParseError("weeks is missing. Use a list of weeks, or an empty list.")
    weeks = payload["weeks"]
    if not isinstance(weeks, list):
        raise CalendarParseError("weeks must be a list of weeks, or an empty list.")
    days: list[Day] = []
    seen: set[date] = set()
    for index, week in enumerate(weeks, start=1):
        if not isinstance(week, list):
            raise CalendarParseError(f"week {index} must be a list of days.")
        for raw in week:
            parsed = _parse_day(raw)
            # A repeated date used to load, and the later entry silently
            # replaced the earlier one's count and level in the grid.
            if parsed.date in seen:
                raise CalendarParseError(
                    f"day {parsed.date.isoformat()} appears more than once. List each date once."
                )
            seen.add(parsed.date)
            days.append(parsed)
    try:
        return calendar_from_days(str(payload.get("username", "")), start, end, days)
    except ValueError as exc:
        raise CalendarParseError(str(exc)) from None


def calendar_to_json(cal: Calendar) -> dict:
    return {
        "username": cal.username,
        "total": cal.total,
        "start": cal.start.isoformat(),
        "end": cal.end.isoformat(),
        "weeks": [
            [
                {"date": day.date.isoformat(), "count": day.count, "level": day.level}
                for day in week
            ]
            for week in cal.weeks
        ],
    }


class GraphQLError(RuntimeError):
    pass


def _graphql(token: str, query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "tetris-contrib",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise GraphQLError(f"GitHub GraphQL HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise GraphQLError(f"GitHub GraphQL request failed: {exc.reason}") from exc
    if payload.get("errors"):
        message = "; ".join(str(item.get("message", item)) for item in payload["errors"])
        raise GraphQLError(message)
    return payload["data"]


def fetch_calendar(username: str, token: str, today: date | None = None) -> Calendar:
    """Fetch the profile contribution window for ``username``."""
    today = today or datetime.now(timezone.utc).date()
    start, end = profile_window(today)
    if range_exceeds_one_year(start, end):
        # The profile grid opens on the Sunday of the week one year ago and
        # closes on Saturday of this week, so it is always a few days over
        # a year. GitHub rejects that range. The default collection is the
        # graph the profile draws; ask for it instead of sending a query
        # that fails on every run.
        data = _graphql(token, QUERY_DEFAULT, {"login": username})
    else:
        variables = {
            "login": username,
            "from": f"{start.isoformat()}T00:00:00Z",
            "to": f"{end.isoformat()}T23:59:59Z",
        }
        try:
            data = _graphql(token, QUERY, variables)
        except GraphQLError as exc:
            if "year" not in str(exc).lower():
                raise
            # A shorter range can still land on the anniversary. The default
            # collection is the same graph the profile draws.
            data = _graphql(token, QUERY_DEFAULT, {"login": username})
    user = data.get("user")
    if not user:
        raise GraphQLError(f"GitHub user {username!r} was not found")
    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    days = [_parse_day(raw) for week in weeks for raw in week["contributionDays"]]
    if not days:
        raise GraphQLError(f"no contribution days returned for {username}")
    # Trust the dates GitHub returned when they already form the profile grid.
    got_start = min(day.date for day in days)
    got_end = max(day.date for day in days)
    if (got_end - got_start).days % 7 == 6:
        start, end = got_start, got_end
    return calendar_from_days(username, start, end, days)


def normalize(cells: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    items = list(cells)
    min_row = min(row for row, _col in items)
    min_col = min(col for _row, col in items)
    return tuple(sorted((row - min_row, col - min_col) for row, col in items))


def rotations(shape: Sequence[tuple[int, int]]) -> tuple[tuple[tuple[int, int], ...], ...]:
    found: list[tuple[tuple[int, int], ...]] = []
    current = tuple(shape)
    for _ in range(4):
        norm = normalize(current)
        if norm not in found:
            found.append(norm)
        current = tuple((col, -row) for row, col in current)
    return tuple(found)


def _orientations() -> list[tuple[str, tuple[tuple[int, int], ...]]]:
    ordered: list[tuple[str, tuple[tuple[int, int], ...]]] = []
    for table in (TETROMINOES, SMALL_PIECES):
        for name, shape in table.items():
            for orientation in rotations(shape):
                ordered.append((name, orientation))
    return ordered


ORIENTATIONS = _orientations()
SHAPE_NAME = {orientation: name for name, orientation in ORIENTATIONS}


def match_shape(cells: Iterable[tuple[int, int]]) -> str | None:
    return SHAPE_NAME.get(normalize(cells))


def _badness(cells: set[tuple[int, int]]) -> tuple[int, int, int]:
    """How awkward the uncovered cells are for a later tetromino tiling."""
    if not cells:
        return (0, 0, 0)
    remaining = set(cells)
    odd = isolates = tiny = 0
    while remaining:
        start = remaining.pop()
        stack = [start]
        size = 1
        while stack:
            row, col = stack.pop()
            for neighbor in ((row + 1, col), (row - 1, col), (row, col + 1), (row, col - 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
                    size += 1
        if size % 4:
            odd += 1
        if size == 1:
            isolates += 1
        if size < 4:
            tiny += 1
    return (odd, isolates, tiny)


def _placements(anchor: tuple[int, int], free: set[tuple[int, int]]) -> list[Piece]:
    row, col = anchor
    found: dict[tuple[tuple[int, int], ...], str] = {}
    for name, orientation in ORIENTATIONS:
        for origin_row, origin_col in orientation:
            delta_row = row - origin_row
            delta_col = col - origin_col
            placed = tuple(
                sorted((cell_row + delta_row, cell_col + delta_col) for cell_row, cell_col in orientation)
            )
            if all(cell in free for cell in placed):
                found.setdefault(placed, name)
    return [Piece(name, cells) for cells, name in found.items()]


def _variety(piece: Piece, anchor: tuple[int, int]) -> int:
    """Spread shapes and rotations across the board without using randomness."""
    mix = 0
    for row, col in piece.cells:
        mix = (mix * 5 + row * 2 + col) % 97
    order = ("O", "T", "L", "J", "S", "Z", "I", "L3", "I3", "I2", "I1")
    base = order.index(piece.name) if piece.name in order else len(order)
    return (base * 3 + mix + anchor[0] * 7 + anchor[1] * 11) % 19


def _greedy(rows: int, cols: int, seed: int = 0) -> list[Piece]:
    """Largest-piece frontier pack, used for small or odd regions."""
    free = {(row, col) for row in range(rows) for col in range(cols)}
    pieces: list[Piece] = []
    while free:
        anchor = min(free)
        candidates = _placements(anchor, free)
        if not candidates:
            raise RuntimeError(f"no piece fits at {anchor}")

        def rank(piece: Piece) -> tuple:
            rest = free.difference(piece.cells)
            # seed 0 leaves the historical variety order unchanged.
            variety = (_variety(piece, anchor) + seed) % 19
            return (-piece.size, _badness(rest), variety, piece.cells)

        chosen = min(candidates, key=rank)
        pieces.append(chosen)
        free.difference_update(chosen.cells)
    return _weld(pieces)


_TETROMINO_ORIENTATIONS = tuple(
    (name, orientation) for name, orientation in ORIENTATIONS if len(orientation) == 4
)


def _exact_tetrominoes(rows: int, cols: int, bias: int) -> list[Piece]:
    """Tile a small rectangle with tetrominoes only. Backtracking stays shallow."""
    free = {(row, col) for row in range(rows) for col in range(cols)}

    def candidates(anchor: tuple[int, int], open_cells: set[tuple[int, int]]) -> list[Piece]:
        found: dict[tuple[tuple[int, int], ...], Piece] = {}
        row, col = anchor
        for name, orientation in _TETROMINO_ORIENTATIONS:
            for origin_row, origin_col in orientation:
                delta_row = row - origin_row
                delta_col = col - origin_col
                placed = tuple(
                    sorted(
                        (cell_row + delta_row, cell_col + delta_col) for cell_row, cell_col in orientation
                    )
                )
                if all(cell in open_cells for cell in placed):
                    found.setdefault(placed, Piece(name, placed))
        ordered = list(found.values())
        ordered.sort(key=lambda piece: ((_variety(piece, anchor) + bias) % 19, piece.cells))
        return ordered

    def search(open_cells: set[tuple[int, int]]) -> list[Piece] | None:
        if not open_cells:
            return []
        anchor = min(open_cells)
        for piece in candidates(anchor, open_cells):
            found = search(open_cells.difference(piece.cells))
            if found is not None:
                return [piece, *found]
        return None

    found = search(free)
    if found is None:
        raise RuntimeError(f"no tetromino tiling for {rows}x{cols}")
    return found


def _shift(pieces: Sequence[Piece], row_offset: int, col_offset: int) -> list[Piece]:
    moved: list[Piece] = []
    for piece in pieces:
        cells = tuple(sorted((row + row_offset, col + col_offset) for row, col in piece.cells))
        moved.append(Piece(piece.name, cells))
    return moved


def _tile_band(row_offset: int, band_rows: int, cols: int, bias_salt: int, seed: int = 0) -> list[Piece]:
    """Tile a horizontal band. Widths of 4 are solved exactly; the tail may be smaller."""
    pieces: list[Piece] = []
    block = 0
    col = 0
    while col + 4 <= cols:
        local = _exact_tetrominoes(band_rows, 4, bias=bias_salt + block * 5)
        pieces.extend(_shift(local, row_offset, col))
        col += 4
        block += 1
    if col < cols:
        width = cols - col
        if band_rows * width % 4 == 0:
            local = _exact_tetrominoes(band_rows, width, bias=bias_salt + 3)
            pieces.extend(_shift(local, row_offset, col))
        else:
            pieces.extend(_shift(_greedy(band_rows, width, seed), row_offset, col))
    return pieces


def decompose(rows: int, cols: int, seed: int = 0) -> list[Piece]:
    """Pack a solid grid into catalog pieces.

    A profile calendar is 7 rows. The top 4 and bottom 3 are tiled separately,
    because each 4-column block of those bands divides evenly into tetrominoes.
    The only leftovers are the few cells required by ``7 * columns`` modulo 4.
    Other sizes use a largest-first frontier pack.

    ``seed`` 0 is that stable pack. Another integer only reorders equally
    legal tetromino choices; the cells still lock on the same days.
    """
    if rows == 7 and cols >= 1:
        pieces = _tile_band(0, 4, cols, bias_salt=1 + seed, seed=seed)
        pieces.extend(_tile_band(4, 3, cols, bias_salt=8 + seed, seed=seed))
        return _weld(pieces)
    return _greedy(rows, cols, seed)


def _weld(pieces: list[Piece]) -> list[Piece]:
    """Join adjacent sub-tetromino leftovers when they form a real piece."""
    current = list(pieces)
    changed = True
    while changed:
        changed = False
        small = [index for index, piece in enumerate(current) if piece.size < 4]
        for left in range(len(small)):
            for right in range(left + 1, len(small)):
                first = current[small[left]]
                second = current[small[right]]
                union = tuple(sorted(first.cells + second.cells))
                if len(union) > 4:
                    continue
                name = match_shape(union)
                if name is None or len(union) <= max(first.size, second.size):
                    continue
                current[small[left]] = Piece(name, union)
                current.pop(small[right])
                changed = True
                break
            if changed:
                break
    return current


def lands_before(earlier: Piece, later: Piece) -> bool:
    """True when ``earlier`` has a cell under ``later`` in the same column.

    A brick falls straight down, so anything already locked above its path
    would be flown through. Bottom cells in a shared column land first.
    """
    lowest: dict[int, int] = {}
    for row, col in earlier.cells:
        lowest[col] = max(row, lowest.get(col, -1))
    return any(col in lowest and lowest[col] > row for row, col in later.cells)


def stack_order(pieces: Sequence[Piece]) -> list[Piece]:
    """Land supporting bricks first, sweeping the year left to right."""
    count = len(pieces)
    incoming = [0] * count
    followers: list[list[int]] = [[] for _ in range(count)]
    for earlier in range(count):
        for later in range(count):
            if earlier != later and lands_before(pieces[earlier], pieces[later]):
                incoming[later] += 1
                followers[earlier].append(later)

    def sort_key(index: int) -> tuple:
        rows = [row for row, _col in pieces[index].cells]
        cols = [col for _row, col in pieces[index].cells]
        return (min(cols), -max(rows), min(rows), pieces[index].name, pieces[index].cells)

    ready = sorted((index for index in range(count) if incoming[index] == 0), key=sort_key)
    ordered: list[int] = []
    while ready:
        index = ready.pop(0)
        ordered.append(index)
        unlocked: list[int] = []
        for follower in followers[index]:
            incoming[follower] -= 1
            if incoming[follower] == 0:
                unlocked.append(follower)
        if unlocked:
            ready.extend(unlocked)
            ready.sort(key=sort_key)
    if len(ordered) != count:
        return sorted(pieces, key=sort_key_piece)
    return [pieces[index] for index in ordered]


def sort_key_piece(piece: Piece) -> tuple:
    rows = [row for row, _col in piece.cells]
    cols = [col for _row, col in piece.cells]
    return (min(cols), -max(rows), min(rows), piece.name, piece.cells)


def make_timeline(count: int, drop: float) -> Timeline:
    """One shared clock. Piece ``i`` is delayed so the board stacks in order.

    The finished graph stays up for a few seconds. Pieces then leave in the
    same order and the 0% frame matches the 100% frame, so the loop is seamless.
    """
    fall = 0.58
    bounce = 0.16
    fade = 0.42
    hold = 3.5
    tail = 0.35
    if count <= 1:
        stagger = 0.0
    else:
        stagger = min(0.052, 5.6 / (count - 1))
    delays = tuple(index * stagger for index in range(count))
    last_delay = delays[-1] if delays else 0.0
    last_land = last_delay + (fall if count else 0.0)
    fade_at = last_land + hold
    total = last_delay + fade_at + fade + tail
    return Timeline(
        delays=delays,
        total=total,
        fall=fall,
        bounce=bounce,
        fade_at=fade_at,
        fade=fade,
        drop=drop,
    )


def _mix(color: str, other: tuple[int, int, int], amount: float) -> str:
    value = color.lstrip("#")
    base = tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))
    mixed = tuple(round(base[index] * (1 - amount) + other[index] * amount) for index in range(3))
    return "#{:02x}{:02x}{:02x}".format(*mixed)


def _fmt(number: float) -> str:
    text = f"{number:.4f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _percent(moment: float, total: float) -> str:
    return _fmt(100.0 * moment / total)


def month_labels(cal: Calendar) -> list[tuple[int, str]]:
    labels: list[tuple[int, str]] = []
    last_col = -3
    for col, week in enumerate(cal.weeks):
        first_of_month = next((day for day in week if day.date.day == 1), None)
        if col == 0 and first_of_month is None:
            labels.append((0, week[0].date.strftime("%b")))
            last_col = 0
            continue
        if first_of_month is not None and col - last_col >= 2:
            labels.append((col, first_of_month.date.strftime("%b")))
            last_col = col
    return labels


def _brick(level: int, palette: dict[str, object]) -> str:
    colors: tuple[str, ...] = palette["levels"]  # type: ignore[assignment]
    base = colors[level]
    border = str(palette["border"])
    if level == 0:
        return (
            f'<rect width="{CELL}" height="{CELL}" rx="2" fill="{base}" '
            f'stroke="{border}" stroke-width="1"/>'
        )
    highlight = _mix(base, (255, 255, 255), 0.42)
    shade = _mix(base, (0, 0, 0), 0.38)
    stud = _mix(base, (255, 255, 255), 0.20)
    stud_top = _mix(base, (255, 255, 255), 0.55)
    return (
        f'<rect width="{CELL}" height="{CELL}" rx="2" fill="{base}"/>'
        f'<rect x="1" y="0.8" width="9" height="1.15" rx="0.5" fill="{highlight}" opacity="0.55"/>'
        f'<rect x="1" y="9" width="9" height="1.05" rx="0.45" fill="{shade}" opacity="0.4"/>'
        f'<rect x="9.35" y="1.5" width="0.9" height="7.6" rx="0.4" fill="{shade}" opacity="0.28"/>'
        f'<circle cx="5.5" cy="5.65" r="1.9" fill="{shade}"/>'
        f'<circle cx="5.5" cy="5.35" r="1.55" fill="{stud}"/>'
        f'<circle cx="4.9" cy="4.75" r="0.48" fill="{stud_top}"/>'
    )


def _joints(piece: Piece, levels: list[list[int]], origin_x: float, origin_y: float, palette: dict) -> str:
    colors: tuple[str, ...] = palette["levels"]  # type: ignore[assignment]
    occupied = set(piece.cells)
    parts: list[str] = []
    for row, col in piece.cells:
        for neighbor, horizontal in (
            ((row, col + 1), True),
            ((row + 1, col), False),
        ):
            if neighbor not in occupied:
                continue
            if levels[row][col] != levels[neighbor[0]][neighbor[1]]:
                continue
            color = colors[levels[row][col]]
            if horizontal:
                x = origin_x + col * STEP + CELL - 0.45
                y = origin_y + row * STEP + 1.7
                width, height = GAP + 0.9, CELL - 3.4
            else:
                x = origin_x + col * STEP + 1.7
                y = origin_y + row * STEP + CELL - 0.45
                width, height = CELL - 3.4, GAP + 0.9
            parts.append(
                f'<rect x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(width)}" height="{_fmt(height)}" '
                f'rx="0.6" fill="{color}"/>'
            )
    return "".join(parts)


def _at_speed(seconds: float, speed: float) -> float:
    """Scale one timeline value by a positive speed multiplier.

    A speed of 1 returns ``seconds`` unchanged, so the default SVG stays
    byte-for-byte the same. Larger speeds shorten every delay and the loop.
    """
    if speed == 1.0:
        return seconds
    return seconds / speed


def _fall_css(timeline: Timeline, speed: float = 1.0) -> str:
    drop = timeline.drop
    fall = timeline.fall
    bounce = timeline.bounce
    fade_at = timeline.fade_at
    fade_end = fade_at + timeline.fade
    total = timeline.total
    # Ease-out is baked into keyframe spacing so the whole loop can stay linear.
    stops = [
        (0.0, -drop, 0),
        (0.05, -drop, 1),
        (fall * 0.32, -drop * 0.20, 1),
        (fall * 0.68, -drop * 0.035, 1),
        (fall, 0.0, 1),
        (fall + bounce * 0.42, -3.4, 1),
        (fall + bounce, 0.0, 1),
        (fade_at, 0.0, 1),
        (fade_end, 0.0, 0),
        (total, -drop, 0),
    ]
    body = []
    for moment, y_pos, opacity in stops:
        body.append(
            f"{_percent(moment, total)}%{{transform:translateY({_fmt(y_pos)}px);opacity:{opacity}}}"
        )
    lock_end = fall + bounce + 0.18
    lock = (
        f"0%{{opacity:1}}"
        f"{_percent(fall + bounce, total)}%{{opacity:1}}"
        f"{_percent(lock_end, total)}%{{opacity:0}}"
        f"100%{{opacity:0}}"
    )
    duration = _fmt(_at_speed(total, speed))
    return (
        ".piece{animation:fall "
        + duration
        + "s linear infinite;animation-fill-mode:backwards}"
        ".joints{animation:lock "
        + duration
        + "s linear infinite;animation-fill-mode:backwards}"
        "@keyframes fall{" + "".join(body) + "}"
        "@keyframes lock{" + lock + "}"
        "@media (prefers-reduced-motion:reduce){"
        ".piece,.joints{animation:none}"
        ".piece{transform:none;opacity:1}"
        ".joints{opacity:0}}"
    )


# After the bricks settle, hold the Chinese palette, then sweep from
# left to right. The whole wave is about 1.8s; each week column's top
# layer crumbles in 0.35s, and ash particles fall for 0.6s. Later
# columns start later, so the change reads as a wave.
TONE_HOLD = 0.7
TONE_SWEEP = 1.8
TONE_COLUMN_FADE = 0.35
TONE_DUST_FADE = 0.6
DUST_SEED = 20261110
DUST_PER_CELL = 3


def _mix32(value: int) -> int:
    """A small integer mix used for deterministic ash particle offsets."""
    value &= 0xFFFFFFFF
    value ^= (value << 13) & 0xFFFFFFFF
    value ^= value >> 17
    value ^= (value << 5) & 0xFFFFFFFF
    return value & 0xFFFFFFFF


def dust_specs(
    col: int,
    row: int,
    count: int = DUST_PER_CELL,
    seed: int = DUST_SEED,
) -> tuple[tuple[float, float, float, float], ...]:
    """Return ``count`` ash particles as ``(ox, oy, dx, dy)`` pixel offsets.

    ``ox`` and ``oy`` are positions inside the 11px cell. ``dx`` and
    ``dy`` are the drift to the right and down as the ash falls. The
    values are deterministic for a given cell and ``seed``.
    """
    if count < 0:
        raise ValueError("dust particle count cannot be negative")
    specs: list[tuple[float, float, float, float]] = []
    state = _mix32(seed ^ ((col + 1) * 0x9E3779B9) ^ ((row + 3) * 0x85EBCA6B))
    for index in range(count):
        state = _mix32(state ^ ((index + 1) * 0xC2B2AE35) ^ 0x27D4EB2D)
        u1 = (state & 0xFFFF) / 65535.0
        state = _mix32(state + 0x9E3779B9)
        u2 = (state & 0xFFFF) / 65535.0
        state = _mix32(state + 0x7F4A7C15)
        u3 = (state & 0xFFFF) / 65535.0
        state = _mix32(state + 0x94D049BB)
        u4 = (state & 0xFFFF) / 65535.0
        ox = 1.2 + u1 * (CELL - 3.6)
        oy = 1.2 + u2 * (CELL - 3.6)
        dx = 1.6 + u3 * 6.5
        dy = 5.0 + u4 * 10.0
        specs.append((ox, oy, dx, dy))
    return tuple(specs)


def _tone_schedule(timeline: Timeline, columns: int) -> tuple[float, float, float, float]:
    """Return ``(start_at, stagger, column_fade, dust_fade)`` in seconds.

    ``start_at`` is when column 0 begins to crumble. Column ``i`` starts
    ``i * stagger`` later. The top layer finishes ``column_fade`` after
    that, and the ash particles finish ``dust_fade`` after the start.
    The last column's top layer finishes about ``TONE_SWEEP`` after
    column 0 starts, still before the bricks leave.
    """
    last_delay = timeline.delays[-1] if timeline.delays else 0.0
    settled = last_delay + timeline.fall + timeline.bounce
    start_at = settled + TONE_HOLD
    sweep = TONE_SWEEP
    column_fade = TONE_COLUMN_FADE
    dust_fade = TONE_DUST_FADE
    latest_done = timeline.fade_at - 0.6
    trail = max(0.0, dust_fade - column_fade)
    if start_at + sweep + trail > latest_done:
        start_at = settled + 0.25
        sweep = max(0.8, latest_done - start_at - trail)
        column_fade = min(column_fade, max(0.2, sweep * 0.25))
        dust_fade = min(dust_fade, column_fade + trail, max(column_fade, latest_done - start_at - (sweep - column_fade)))
        if start_at + sweep + max(0.0, dust_fade - column_fade) > latest_done:
            start_at = settled
            trail = max(0.0, dust_fade - column_fade)
            sweep = max(0.45, latest_done - start_at - trail)
            column_fade = min(column_fade, max(0.15, sweep * 0.25))
            dust_fade = min(dust_fade, max(column_fade, column_fade + 0.15))
    count = max(int(columns), 1)
    stagger = 0.0 if count == 1 else (sweep - column_fade) / (count - 1)
    return start_at, stagger, column_fade, dust_fade


def _tone_css(timeline: Timeline, columns: int, speed: float = 1.0) -> str:
    """Crumble from the starting holiday colors into the ending ones.

    The completed Chinese graph stays visible briefly after the last
    brick lands. Then, left to right, each week's top layer shrinks and
    fades while a few ash particles drift down and to the right,
    revealing the Western palette already underneath. Each column has
    its own keyframes so the stagger repeats on every loop. At 100% the
    top layer jumps back, which is hidden because the pieces have
    already left. Reduced motion shows the end palette on the locked
    graph, with the ash hidden.
    """
    start_at, stagger, column_fade, dust_fade = _tone_schedule(timeline, columns)
    total = timeline.total
    duration = _fmt(_at_speed(total, speed))
    leave_pct = _percent(timeline.fade_at, total)
    count = max(int(columns), 1)
    parts = [
        f".tone-start,.dust{{animation-duration:{duration}s;"
        "animation-timing-function:linear;animation-iteration-count:infinite;"
        "animation-fill-mode:backwards;transform-box:fill-box;transform-origin:center}"
    ]
    for col in range(count):
        fade_start = start_at + col * stagger
        fade_end = fade_start + column_fade
        dust_end = fade_start + dust_fade
        pop_at = fade_start + min(0.05, column_fade * 0.15)
        start_pct = _percent(fade_start, total)
        done_pct = _percent(fade_end, total)
        pop_pct = _percent(pop_at, total)
        dust_pct = _percent(dust_end, total)
        parts.append(
            f"@keyframes ts{col}{{0%,{start_pct}%{{opacity:1;transform:none}}"
            f"{done_pct}%,{leave_pct}%{{opacity:0;transform:translate(1.3px,.8px) scale(.62)}}"
            f"100%{{opacity:1;transform:none}}}}"
            f"@keyframes ds{col}{{0%,{start_pct}%{{opacity:0;transform:translate(0,0)}}"
            f"{pop_pct}%{{opacity:.9;transform:translate(0,0)}}"
            f"{dust_pct}%,{leave_pct}%{{opacity:0;transform:translate(var(--dx),var(--dy))}}"
            f"100%{{opacity:0;transform:translate(0,0)}}}}"
            f".ts{col}{{animation-name:ts{col}}}"
            f".ds{col}{{animation-name:ds{col}}}"
        )
    parts.append(
        "@media (prefers-reduced-motion:reduce){"
        ".tone-start,.dust{animation:none}"
        ".tone-start,.dust{opacity:0}"
        ".tone-end{opacity:1}}"
    )
    return "".join(parts)


def _palette_pair(palette: str | PaletteTransition) -> tuple[str, str | None]:
    """Return ``(start, end)`` palette names. ``end`` is set for a fade."""
    if isinstance(palette, str) and ">" in palette:
        start, end = palette.split(">", 1)
        palette = PaletteTransition(start, end)
    if isinstance(palette, PaletteTransition):
        start, end = palette.start, palette.end
        if start not in PALETTE_TABLES or end not in PALETTE_TABLES or start == end:
            raise ValueError(f"unknown palette {palette!r}")
        return start, end
    if palette not in PALETTE_TABLES:
        raise ValueError(f"unknown palette {palette!r}")
    return palette, None


def render_svg(
    cal: Calendar,
    pieces: Sequence[Piece],
    theme: str,
    *,
    speed: float = 1.0,
    palette: str | PaletteTransition = "default",
) -> str:
    start_name, end_name = _palette_pair(palette)
    themes = PALETTE_TABLES[start_name]
    if theme not in themes:
        raise ValueError(f"unknown theme {theme!r}")
    chosen = themes[theme]
    end_chosen: dict[str, object] | None = None
    if end_name is not None:
        end_themes = PALETTE_TABLES[end_name]
        if theme not in end_themes:
            raise ValueError(f"unknown theme {theme!r}")
        end_chosen = end_themes[theme]
    text = str(chosen["text"])
    columns = cal.columns
    origin_x = 34
    origin_y = 22
    width = max(origin_x + columns * STEP + 16, origin_x + 420)
    height = origin_y + ROWS * STEP + 28
    drop = float(origin_y + (ROWS - 1) * STEP + CELL + 8)
    ordered = stack_order(pieces)
    timeline = make_timeline(len(ordered), drop)
    levels = [[cal.level_at(row, col) for col in range(columns)] for row in range(ROWS)]

    defs = []
    for level in range(5):
        defs.append(f'<g id="b{theme[0]}{level}">{_brick(level, chosen)}</g>')
        if end_chosen is not None and level > 0:
            defs.append(f'<g id="b{theme[0]}{level}e">{_brick(level, end_chosen)}</g>')
            color = chosen["levels"][level]
            defs.append(
                f'<rect id="d{theme[0]}{level}" width="1.6" height="1.6" rx="0.45" fill="{color}"/>'
            )

    def _swatch(level: int, x: float | int, y: float | int, col: int = 0, row: int = 0) -> str:
        start = f'<use href="#b{theme[0]}{level}" x="{x}" y="{y}"/>'
        if end_chosen is None or level == 0:
            return start
        parts = [
            f'<use class="tone-end" href="#b{theme[0]}{level}e" x="{x}" y="{y}"/>',
            f'<g class="tone-start ts{col}">{start}</g>',
        ]
        dust_id = f"d{theme[0]}{level}"
        for ox, oy, dx, dy in dust_specs(col, row):
            parts.append(
                f'<g class="dust ds{col}" style="--dx:{_fmt(dx)}px;--dy:{_fmt(dy)}px">'
                f'<use href="#{dust_id}" x="{_fmt(x + ox)}" y="{_fmt(y + oy)}"/></g>'
            )
        return "".join(parts)

    piece_markup: list[str] = []
    counts: dict[str, int] = {}
    for index, piece in enumerate(ordered):
        counts[piece.name] = counts.get(piece.name, 0) + 1
        delay = _fmt(_at_speed(timeline.delays[index], speed))
        joints = _joints(piece, levels, origin_x, origin_y, chosen)
        cells = []
        for row, col in piece.cells:
            level = levels[row][col]
            x = origin_x + col * STEP
            y = origin_y + row * STEP
            cells.append(_swatch(level, x, y, col, row))
        joint_group = ""
        if joints:
            joint_group = f'<g class="joints" opacity="0" style="animation-delay:{delay}s">{joints}</g>'
        piece_markup.append(
            f'<g class="piece" style="animation-delay:{delay}s">{joint_group}{"".join(cells)}</g>'
        )

    labels = []
    for col, name in month_labels(cal):
        x = origin_x + col * STEP
        labels.append(f'<text x="{x}" y="14">{name}</text>')
    for row, name in LABELED_ROWS.items():
        y = origin_y + row * STEP + 8
        labels.append(f'<text x="26" y="{y}" text-anchor="end" font-size="9">{name}</text>')

    sentence = f"{cal.total} contribution" + ("s" if cal.total != 1 else "") + " in the last year"
    caption_y = origin_y + ROWS * STEP + 18
    legend_x = width - 158
    legend = [f'<text x="{legend_x}" y="{caption_y}">Less</text>']
    for level in range(5):
        x = legend_x + 34 + level * STEP
        y = caption_y - 9
        # The legend follows the last week, so it finishes with the wave.
        legend.append(_swatch(level, x, y, columns - 1 if columns else 0, row=-(level + 1)))
    legend.append(f'<text x="{legend_x + 34 + 5 * STEP + 2}" y="{caption_y}">More</text>')

    summary = " ".join(f"{name}:{counts[name]}" for name in sorted(counts))
    title = f"{cal.username} contributions, built from falling bricks"
    desc = (
        f"{sentence}. Pieces fall into the contribution calendar "
        f"from {cal.start.isoformat()} to {cal.end.isoformat()}."
    )
    css = _fall_css(timeline, speed)
    if end_name is not None:
        css += _tone_css(timeline, columns, speed)
    font = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" overflow="hidden">\n'
        f"<title>{_xml(title)}</title>\n"
        f"<desc>{_xml(desc)}</desc>\n"
        f"<!-- tetris bricks { _xml(cal.username) } {cal.start.isoformat()} {cal.end.isoformat()} {summary} -->\n"
        f"<style>{css}</style>\n"
        f"<defs>{''.join(defs)}</defs>\n"
        f'<g fill="{text}" font-family="{font}" font-size="12">'
        f"{''.join(labels)}"
        f'<text x="{origin_x}" y="{caption_y}">{_xml(sentence)}</text>'
        f"{''.join(legend)}</g>\n"
        f"{''.join(piece_markup)}\n"
        "</svg>\n"
    )


def _xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def pieces_for_calendar(cal: Calendar, seed: int = 0) -> list[Piece]:
    return decompose(ROWS, cal.columns, seed=seed)


def coverage_errors(pieces: Sequence[Piece], rows: int, cols: int) -> list[str]:
    seen: dict[tuple[int, int], int] = {}
    errors: list[str] = []
    for piece in pieces:
        if match_shape(piece.cells) != piece.name:
            errors.append(f"{piece.name} is not a catalog placement of {piece.cells}")
        for cell in piece.cells:
            if cell in seen:
                errors.append(f"overlap at {cell}")
            if not (0 <= cell[0] < rows and 0 <= cell[1] < cols):
                errors.append(f"out of range {cell}")
            seen[cell] = 1
    expected = {(row, col) for row in range(rows) for col in range(cols)}
    missing = expected.difference(seen)
    if missing:
        errors.append(f"missing {len(missing)} cells")
    return errors


def iter_piece_names() -> Iterator[str]:
    yield from list(TETROMINOES) + list(SMALL_PIECES)
