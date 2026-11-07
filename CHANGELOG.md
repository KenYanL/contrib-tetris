# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Dates are the commit dates. `v1.1.0` points at the 2026-10-21 commit and
`v1.2.0` at the 2026-10-27 release, `v1.3.0` at the 2026-11-01 release. `v1`
and `v1.4.0` point at the 2026-11-06 release.

## [Unreleased]

### Added

- Optional `calendar_json` action input. When set to a workspace-relative contribution calendar JSON path (same shape as `sample/contributions.json` / `demo/contributions.json`), the composite action passes it to `generate.py --input` and skips the GitHub API, so `token` is unused. `github_user_name` stays required and still overrides the JSON username label. Omit `calendar_json` to keep fetching the live calendar (2026-11-07).

### Changed

- This repo's [`.github/workflows/tetris.yml`](.github/workflows/tetris.yml) publish job renders the seeded `demo/contributions.json` calendar (`github_user_name: demo`) onto the `output` branch instead of fetching KenYanL's live contribution graph. Pull requests still run tests only (2026-11-07).

## [v1.4.0] - 2026-11-06

### Added

- Optional `lunarnewyear` value for the `palette` input (`--palette lunarnewyear`). Both SVGs use [SchemeColor's Chinese Gold & Red palette](https://www.schemecolor.com/chinese-gold-red.php) (`#ebc862`, `#e4b034`, `#c50100`, `#830010`; `#960316` and `#ca9d08` are dropped as near-duplicates), lightest to darkest. Level 0 stays the neutral empty-cell color from the default graph (`#eff2f5` light, `#151b23` dark). Light levels 1-4 are `#ebc862 #e4b034 #c50100 #830010`. Dark levels 1-4 are `#830010 #c50100 #e4b034 #ebc862`. Lunar New Year falls on a different Gregorian date each year, so `auto` uses a fixed table of UTC dates for 2026-2035 (the first day of the first lunar month in the [Hong Kong Observatory](https://www.hko.gov.hk/en/gts/time/conversion.htm) conversion tables): 2026-02-17, 2027-02-06, 2028-01-26, 2029-02-13, 2030-02-03, 2031-01-23, 2032-02-11, 2033-01-31, 2034-02-19, and 2035-02-08. Christmas covers three UTC days, so Lunar New Year uses that same length: the tabulated day and the two UTC days after it. A year outside the table stays on the green graph. 1 January stays `newyear`; the window never includes it (2026-11-04).
- Optional `newyear` value for the `palette` input (`--palette newyear`). Both SVGs use [Color Hunt's gold gradient palette](https://colorhunt.co/palette/f9e6a8f2a900cc6f004d2a00) (`#f9e6a8`, `#f2a900`, `#cc6f00`, `#4d2a00`), ordered by contrast against the background. Level 0 stays the neutral empty-cell color from the default graph (`#eff2f5` light, `#151b23` dark). Light levels 1-4 are `#f9e6a8 #f2a900 #cc6f00 #4d2a00`. Dark levels 1-4 are `#4d2a00 #cc6f00 #f2a900 #f9e6a8`. `auto` uses that palette on 1 January (UTC) only, keeps Halloween on 31 October (UTC) and Christmas on 24-26 December (UTC), and stays on the green graph every other day, including 31 December and 2 January (2026-11-03).
- Optional `christmas` value for the `palette` input (`--palette christmas`). Both SVGs use [Coolors' most popular Christmas palette](https://coolors.co/palettes/popular/christmas) (`386641`, `6a994e`, `a7c957`, `bc4749`; the cream `f2e8cf` is dropped), ordered by contrast against the background. Level 0 stays the neutral empty-cell color from the default graph (`#eff2f5` light, `#151b23` dark). Light levels 1-4 are `#a7c957 #6a994e #bc4749 #386641`. Dark levels 1-4 are `#386641 #bc4749 #6a994e #a7c957`. `auto` uses that palette on 24, 25, and 26 December (UTC), keeps Halloween on 31 October (UTC), and stays on the green graph every other day (2026-11-02).

### Changed

- `--palette` help is built from `PALETTE_CATALOG` the same way the rejection hint is, so a new holiday cannot drift out of `--help` (2026-11-06).
- Concrete palettes live in one catalog. Each entry has the palette name, its light and dark scales, and the UTC days `auto` selects it. Adding a holiday is that one entry; the name list and the rejection message are built from it. The default, Halloween, and Christmas SVGs are unchanged (2026-11-03).

### Fixed

- A holiday palette whose level 0 drifts from the default empty-cell color is rejected when the catalog is loaded. Light level 0 must stay `#eff2f5` and dark level 0 must stay `#151b23` (2026-11-05).
- `--out` and `--dump-json` fail before any file is written when the path cannot be created, or when `--dump-json` is the output directory or either SVG. A file where a directory is required, a directory where a file is required, and a parent that is a file all name that path. An existing SVG in a real output directory is still replaced (2026-11-04).
- Fetching a contribution calendar no longer sends a ranged GraphQL query that GitHub rejects on every run. The profile window runs from the Sunday of the week one year ago through Saturday of this week, which is always longer than one year, so that query failed and the action retried the default collection. It now asks for the default collection directly. A shorter range that GitHub still rejects for spanning a year falls back the same way (2026-11-01).

## [v1.3.0] - 2026-11-01

### Added

- Optional `palette` input (`--palette` on the CLI). `default` is the usual green contribution graph. `halloween` uses GitHub Primer's Halloween colors (`--contribution-halloween-bgColor-1` through `-4` from `@primer/primitives` 11.10.0) on both the light and dark SVGs. `auto` uses those colors only on 31 October (UTC) and the green graph every other day. Omit the input to keep the green graph (2026-11-01).
- A unit test rebuilds the seeded README demo in a temporary directory and fails when `demo/` drifts from `scripts/make_demo.py`, which now accepts `--out` (default `demo/`) so that check does not overwrite the committed files (2026-10-27).

### Fixed

- A GitHub API failure exits with that error and writes no SVG. An unknown login (`GitHub user '<login>' was not found`), a calendar with no days, and an HTTP or network failure were already raised, but they escaped as a Python traceback (2026-10-31).
- Reloading a `--dump-json` calendar keeps each day's contribution level. The loader reads the integer `level` that `calendar_to_json` writes when `contributionLevel` is absent, so those days still paint colored bricks (2026-10-28).
- The pinned sample SVGs match `sample/contributions.json` again. They were drawn while an integer `level` was ignored, so every cell was an empty brick while the caption still said 168 contributions. A test fails when those files drift from the current renderer (2026-10-29).
- A contribution level outside 0 to 4 is rejected when the calendar is loaded, so the SVG cannot point at a missing brick or paint the wrong quartile. An `--input` file that is missing, not JSON, or otherwise unusable fails with a message that names the file, and no SVG is written (2026-10-30).

## [v1.2.0] - 2026-10-27

### Added

- Invalid `github_user_name`, SVG path, `token`, and `seed` values are rejected before any SVG is written. The message names the input and a valid example: a GitHub login, two different workspace-relative `.svg` paths, a non-empty token, and a `seed` from -2147483648 to 2147483647 (2026-10-22).
- Calendar edge-case tests. A partial first week, and a window that is not already Sunday-to-Saturday, is padded so row 0 stays Sunday and the last row ends on Saturday. Days added by that padding are empty contributions (2026-10-24).
- Optional `speed` input. `1` is the normal pace, `2` plays twice as fast, and `0.5` plays at half speed. The bricks stay the same. An empty value is rejected; omit the input to keep the normal pace (2026-10-25).

### Changed

- The graph at the top of the README is a seeded synthetic demo committed in `demo/`, rebuilt by `scripts/make_demo.py` from a fixed seed. It no longer loads a live calendar from the `output` branch (2026-10-23).

### Fixed

- Demo days are written with `contributionCount` and the `contributionLevel` quartile enum (`NONE`, `FIRST_QUARTILE`, and so on) that `generate.py` reads. The first demo file stored an integer `level`, which the loader ignores, so every demo brick rendered as empty. Both SVGs were regenerated from the same seed, and a test fails when a nonempty calendar paints no colored bricks (2026-10-23).

## [v1] - 2026-10-21

### Added

- Reusable composite action that draws a contribution graph as falling Tetris bricks with LEGO studs. Cells are packed into tetrominoes, with a tromino, domino, or single brick when the grid is not divisible by 4. It writes one animated light SVG and one animated dark SVG, with tests, an MIT license, a pinned sample calendar, and a daily workflow that publishes the SVGs to the `output` branch (2026-10-18).
- Live animation preview at the top of the README, loaded from the `output` branch (2026-10-20).
- Repository-description tagline and a usage FAQ: profile README snippet, which branch the SVGs are published to, schedule, token and permissions, why the display name differs from `uses:`, file size, and empty or very small calendars (2026-10-21).

### Changed

- Display name renamed from Contribution Tetris to Contribution Brickfall. The Marketplace name Contribution Tetris was already taken. The repository slug and `uses:` references stay `contrib-tetris` (2026-10-19).

[Unreleased]: https://github.com/KenYanL/contrib-tetris/compare/v1.4.0...HEAD
[v1.4.0]: https://github.com/KenYanL/contrib-tetris/compare/v1.3.0...v1.4.0
[v1.3.0]: https://github.com/KenYanL/contrib-tetris/compare/v1.2.0...v1.3.0
[v1.2.0]: https://github.com/KenYanL/contrib-tetris/compare/v1.1.0...v1.2.0
[v1]: https://github.com/KenYanL/contrib-tetris/releases/tag/v1
