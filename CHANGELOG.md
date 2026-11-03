# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Dates are the commit dates. `v1.1.0` points at the 2026-10-21 commit and
`v1.2.0` at the 2026-10-27 release. `v1` and `v1.3.0` point at the 2026-11-01
release.

## [Unreleased]

### Added

- Optional `christmas` value for the `palette` input (`--palette christmas`). Both SVGs use [Coolors' most popular Christmas palette](https://coolors.co/palettes/popular/christmas) (`386641`, `6a994e`, `a7c957`, `bc4749`; the cream `f2e8cf` is dropped), ordered by contrast against the background. Level 0 stays the neutral empty-cell color from the default graph (`#eff2f5` light, `#151b23` dark). Light levels 1-4 are `#a7c957 #6a994e #bc4749 #386641`. Dark levels 1-4 are `#386641 #bc4749 #6a994e #a7c957`. `auto` uses that palette on 24, 25, and 26 December (UTC), keeps Halloween on 31 October (UTC), and stays on the green graph every other day (2026-11-02).

### Changed

- Concrete palettes live in one catalog. Each entry has the palette name, its light and dark scales, and the UTC days `auto` selects it. Adding a holiday is that one entry; the name list and the rejection message are built from it. `auto` still uses Halloween on 31 October, Christmas on 24-26 December, and the green graph every other day, including 31 December, 1 January, and 29 February. The SVGs are unchanged (2026-11-03).

### Fixed

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

[Unreleased]: https://github.com/KenYanL/contrib-tetris/compare/v1.3.0...HEAD
[v1.3.0]: https://github.com/KenYanL/contrib-tetris/compare/v1.2.0...v1.3.0
[v1.2.0]: https://github.com/KenYanL/contrib-tetris/compare/v1.1.0...v1.2.0
[v1]: https://github.com/KenYanL/contrib-tetris/releases/tag/v1
