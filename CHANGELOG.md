# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Dates are the commit dates. `v1.1.0` points at the 2026-10-21 commit. `v1`
and `v1.2.0` point at the 2026-10-27 release.

## [Unreleased]

### Added

- A unit test rebuilds the seeded README demo in a temporary directory and fails when `demo/` drifts from `scripts/make_demo.py`, which now accepts `--out` (default `demo/`) so that check does not overwrite the committed files (2026-10-27).

### Fixed

- Reloading a `--dump-json` calendar keeps each day's contribution level. The loader reads the integer `level` that `calendar_to_json` writes when `contributionLevel` is absent, so those days still paint colored bricks (2026-10-28).

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

[Unreleased]: https://github.com/KenYanL/contrib-tetris/compare/v1.2.0...HEAD
[v1.2.0]: https://github.com/KenYanL/contrib-tetris/compare/v1.1.0...v1.2.0
[v1]: https://github.com/KenYanL/contrib-tetris/releases/tag/v1
