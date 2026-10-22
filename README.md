# contrib-tetris

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/KenYanL/contrib-tetris/output/tetris-contrib-dark.svg" />
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/KenYanL/contrib-tetris/output/tetris-contrib.svg" />
  <img alt="KenYanL contribution graph assembling from Tetris bricks" src="https://raw.githubusercontent.com/KenYanL/contrib-tetris/output/tetris-contrib.svg" />
</picture>

KenYanL's real contribution graph, rebuilt by falling bricks and refreshed daily.

*Reusable GitHub Action that renders a contribution graph as falling Tetris and LEGO bricks and writes one animated light SVG and one animated dark SVG.*

Contribution Brickfall (formerly Contribution Tetris) is a reusable GitHub Action that draws a contribution graph as falling Tetris bricks with LEGO studs. Pieces drop in and lock on the days they belong to, so the resting frame is the real calendar. Light and dark are separate animated SVGs, pure SVG and CSS, about 50KB each, with no extra packages.

That preview is this HTML:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/KenYanL/contrib-tetris/output/tetris-contrib-dark.svg" />
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/KenYanL/contrib-tetris/output/tetris-contrib.svg" />
  <img alt="KenYanL contribution graph assembling from Tetris bricks" src="https://raw.githubusercontent.com/KenYanL/contrib-tetris/output/tetris-contrib.svg" />
</picture>
```

The daily workflow republishes those two files on the [`output`](https://github.com/KenYanL/contrib-tetris/tree/output) branch. `sample/` is a pinned copy of KenYanL's calendar for 2025-10-12 through 2026-10-17 (168 contributions).

## Use it

```yaml
name: Generate contribution tetris

on:
  schedule:
    - cron: "41 7 * * *"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: KenYanL/contrib-tetris@v1
        with:
          github_user_name: ${{ github.repository_owner }}
          svg_light_path: dist/tetris-contrib.svg
          svg_dark_path: dist/tetris-contrib-dark.svg
          # token: ${{ secrets.GITHUB_TOKEN }}  # optional; defaults to the workflow token
          # seed: "1"                            # optional; omit for the stable pack

      - name: Publish SVGs to the output branch
        uses: crazy-max/ghaction-github-pages@v5
        with:
          target_branch: output
          build_dir: dist
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

Put this in the profile README. Swap in the repository that owns the `output` branch:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_USERNAME/output/tetris-contrib-dark.svg" />
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_USERNAME/output/tetris-contrib.svg" />
  <img alt="Contribution graph assembling from Tetris bricks" src="https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_USERNAME/output/tetris-contrib.svg" />
</picture>
```

The public contribution calendar is readable with the default workflow token.

### Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `github_user_name` | yes | | GitHub login whose calendar is drawn. |
| `svg_light_path` | no | `dist/tetris-contrib.svg` | Where to write the light SVG. |
| `svg_dark_path` | no | `dist/tetris-contrib-dark.svg` | Where to write the dark SVG. |
| `token` | no | workflow token | Token for the GraphQL contribution query. |
| `seed` | no | `0` | Same seed, same bricks. `0` is the stable pack. |

Invalid values fail the step before any SVG is written. The message names the input and a valid example: a GitHub login, two different workspace-relative `.svg` paths, a non-empty token, and a `seed` from -2147483648 to 2147483647.

### Outputs

| Output | Description |
| --- | --- |
| `svg_light_path` | Path of the light SVG that was written. |
| `svg_dark_path` | Path of the dark SVG that was written. |

## FAQ

### How do I show it on a profile README?

Paste the `<picture>` block from [Use it](#use-it) into the README of the repository that publishes the SVGs. For a GitHub profile, that repository is `YOUR_USERNAME/YOUR_USERNAME`. The first `<source>` is the dark SVG (`prefers-color-scheme: dark`), the second is the light SVG, and the `<img>` is the light file. Those URLs load the files from the `output` branch: `https://raw.githubusercontent.com/OWNER/REPO/output/tetris-contrib.svg` and `tetris-contrib-dark.svg`.

### Which branch do the SVGs get published to, and why?

The action writes both files in the job workspace. The defaults are `dist/tetris-contrib.svg` and `dist/tetris-contrib-dark.svg`. The example workflow then publishes the `dist/` directory to a branch named `output` with `crazy-max/ghaction-github-pages`, so those SVGs sit at the root of that branch and the raw URLs above resolve. `main` stays the action source. This repo's [`.github/workflows/tetris.yml`](.github/workflows/tetris.yml) does the same publish, and the publish job runs on the daily schedule, on `workflow_dispatch`, and on pushes to `main`. Pull requests run the test job only.

### How often does it update, and how do I change the schedule?

The schedule is the workflow's cron. The example and this repo both use `41 7 * * *` (07:41 UTC every day). Both also set `workflow_dispatch`, so the workflow can be run from the Actions tab. Change that cron to change how often the SVGs are regenerated.

### What token and permissions does it need?

`token` defaults to the calling workflow's `GITHUB_TOKEN` (`${{ github.token }}`). The action sends it as a bearer token to `https://api.github.com/graphql` and reads that login's contribution calendar. The public calendar is readable with that default token. An empty token fails the step. Publishing the `output` branch needs `contents: write` on the job that pushes. The example sets that at the workflow level. This repo's workflow leaves the default at `contents: read` and sets `contents: write` only on the publish job.

### Why is the name Contribution Brickfall when usage is `uses: KenYanL/contrib-tetris@v1`?

`name: Contribution Brickfall` in [`action.yml`](action.yml) is the display name. The action was formerly Contribution Tetris. `uses:` selects the repository and the ref, which are still `KenYanL/contrib-tetris` and `v1`, so the workflow line stays `uses: KenYanL/contrib-tetris@v1`.

### How big are the files, and does it install anything?

The action installs nothing. It runs `generate.py` with Python 3.10 or newer from the standard library, which `ubuntu-latest` already has. Each result is pure SVG and CSS (no `<script>`). The pinned sample in `sample/` is 48,956 bytes (light) and 48,959 bytes (dark). `generate.py` prints the byte size of each file as it writes it.

### What happens with an empty or very small calendar?

Days with no activity are still drawn. Level 0 is a flat square with no stud, and the caption is the real total: `0 contributions in the last year`, or `1 contribution in the last year` when the total is 1. If the API returns no days, the action fails with `no contribution days returned for <login>`. An unknown login fails with `GitHub user '<login>' was not found`. The board is 7 rows by the weeks in the profile window (53 in the pinned sample), and every cell is covered. When `7 × weeks` is not divisible by 4, the leftover cells are a tromino, a domino, or a single brick. The pinned 53-week sample leaves 3 such cells.

## How it is drawn

The profile grid is 7 rows by about 53 weeks. Those cells are packed into I, O, T, S, Z, L, and J tetrominoes, rotations included. `7 × columns` is not always divisible by 4, so the remainder becomes a tromino, domino, or single brick. Each cell keeps that day's contribution level. Days with activity get a stud and a bevel; empty days stay flat squares. One CSS animation drops the pieces. If animation is disabled, the finished graph remains.

Colors are the contribution colors shipped on github.com: light `#eff2f5 #aceebb #4ac26b #2da44e #116329`, dark `#151b23 #033a16 #196c2e #2ea043 #56d364`.

## Develop

No third-party packages. Python 3.10 or newer.

```bash
python3 -m unittest test_brickfall.py
python3 generate.py --input sample/contributions.json --out dist
python3 generate.py --username KenYanL --token "$GITHUB_TOKEN" --out dist
```

`.github/workflows/tetris.yml` runs the tests on every push and pull request. On a daily cron (`41 7 * * *`), on `workflow_dispatch`, and on pushes to `main`, it renders KenYanL's calendar and writes:

- `tetris-contrib.svg`
- `tetris-contrib-dark.svg`

to the `output` branch only.

## Prior art & credits

Similar projects exist. None of their code is copied or wrapped. This generator was written for this repo.

| Project | License | What it does | How this differs |
| --- | --- | --- | --- |
| [debba/gh-contributions-tetris-gif-maker](https://github.com/debba/gh-contributions-tetris-gif-maker) | MIT | Single 1×1 cells fall down each column into place. GIF only, Python/Pillow. | Whole tetrominoes (with smaller leftovers) lock into the real 7×53 grid. Pure SVG/CSS, light and dark. |
| [leereilly/contribution-graph-art](https://github.com/leereilly/contribution-graph-art) | none | Tetrominoes fall through the graph as decoration. They do not build it. | Pieces land on the exact cells of the contribution calendar and stay there until the loop resets. |
| [JuhaP2/contribution-tetris](https://github.com/JuhaP2/contribution-tetris) | MIT | A bot plays a real game on a 10×20 board. | The board is the contribution grid, not a separate Tetris well. |
| [arndom/github-contribution-tetris](https://github.com/arndom/github-contribution-tetris) | MIT, archived | Splits a graph into tetrominoes for a game you play in the browser. | The split is automatic and played back as a README SVG. No game loop to play. |
| [Sur1ive/contribution-fx](https://github.com/Sur1ive/contribution-fx) | MIT | Gravity, plus other effects: cells drop to the bottom of the column and float back. | Cells do not pile up at the bottom. Each brick locks in its real week and weekday. |

The idea that a contribution grid can be shown as falling blocks is shared with those projects. The packer, the LEGO studs, the SVG timeline, and the workflow are separate.

## License

[MIT](LICENSE). Copyright (c) 2026 KenYanL.
