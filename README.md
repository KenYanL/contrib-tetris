# contrib-tetris

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/KenYanL/contrib-tetris/main/demo/tetris-contrib-dark.svg" />
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/KenYanL/contrib-tetris/main/demo/tetris-contrib.svg" />
  <img alt="Demo contribution graph assembling from Tetris bricks" src="https://raw.githubusercontent.com/KenYanL/contrib-tetris/main/demo/tetris-contrib.svg" />
</picture>

A demo with randomly generated contributions, rebuilt by falling bricks.

*Reusable GitHub Action that renders a contribution graph as falling Tetris and LEGO bricks and writes one animated light SVG and one animated dark SVG.*

Contribution Brickfall (formerly Contribution Tetris) is a reusable GitHub Action that draws a contribution graph as falling Tetris bricks with LEGO studs. Pieces drop in and lock on the days they belong to, so the resting frame is the real calendar. Light and dark are separate animated SVGs, pure SVG and CSS, about 50KB each, with no extra packages.

That preview is this HTML:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/KenYanL/contrib-tetris/main/demo/tetris-contrib-dark.svg" />
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/KenYanL/contrib-tetris/main/demo/tetris-contrib.svg" />
  <img alt="Demo contribution graph assembling from Tetris bricks" src="https://raw.githubusercontent.com/KenYanL/contrib-tetris/main/demo/tetris-contrib.svg" />
</picture>
```

Those files are committed in `demo/`. `scripts/make_demo.py` rebuilds them from a fixed random seed. `sample/` is a pinned copy of KenYanL's calendar for 2025-10-12 through 2026-10-17 (168 contributions).

See [CHANGELOG.md](CHANGELOG.md) for the history of this action.

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
          # speed: "1.0"                         # optional; 2 plays twice as fast, 0.5 at half speed
          # palette: default                     # optional; halloween, christmas, or auto

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
| `speed` | no | `1.0` | Animation speed. `1` is the normal pace. `2` plays twice as fast and `0.5` plays at half speed. The bricks stay the same. |
| `palette` | no | `default` | Contribution colors for both SVGs. `default` is the usual green graph. `halloween` uses GitHub's Halloween colors. `christmas` uses a red and green graph. `auto` uses Halloween on 31 October (UTC), Christmas on 24-26 December (UTC), and green every other UTC day. |

Invalid values fail the step before any SVG is written. The message names the input and a valid example: a GitHub login, two different workspace-relative `.svg` paths, a non-empty token, a `seed` from -2147483648 to 2147483647, a positive `speed` such as `1`, `2`, or `0.5`, and a `palette` of `default`, `halloween`, `christmas`, or `auto`.

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

The action installs nothing. It runs `generate.py` with Python 3.10 or newer from the standard library, which `ubuntu-latest` already has. Each result is pure SVG and CSS (no `<script>`). The pinned sample in `sample/` is 45,354 bytes (light) and 45,357 bytes (dark). `generate.py` prints the byte size of each file as it writes it.

### What happens with an empty or very small calendar?

Days with no activity are still drawn. Level 0 is a flat square with no stud, and the caption is the real total: `0 contributions in the last year`, or `1 contribution in the last year` when the total is 1. If the API returns no days, the action fails with `no contribution days returned for <login>`. An unknown login fails with `GitHub user '<login>' was not found`. A rejected token or a network error fails with the GitHub error. In each of those cases the step prints that reason and writes no SVG. The board is 7 rows by the weeks in the profile window (53 in the pinned sample), and every cell is covered. When `7 × weeks` is not divisible by 4, the leftover cells are a tromino, a domino, or a single brick. The pinned 53-week sample leaves 3 such cells.

## How it is drawn

The profile grid is 7 rows by about 53 weeks. Those cells are packed into I, O, T, S, Z, L, and J tetrominoes, rotations included. `7 × columns` is not always divisible by 4, so the remainder becomes a tromino, domino, or single brick. Each cell keeps that day's contribution level. Days with activity get a stud and a bevel; empty days stay flat squares. One CSS animation drops the pieces. If animation is disabled, the finished graph remains.

Colors follow the contribution graph shipped on github.com. The default palette is Primer `--contribution-default-bgColor-0` through `-4`: light `#eff2f5 #aceebb #4ac26b #2da44e #116329`, dark `#151b23 #033a16 #196c2e #2ea043 #56d364`.

`palette: halloween` (CLI: `--palette halloween`) paints both SVGs with Primer `--contribution-halloween-bgColor-1` through `-4` from [@primer/primitives](https://github.com/primer/primitives) 11.10.0 (`dist/css/functional/themes/light.css` and `dark.css`). Level 0 keeps `--contribution-default-bgColor-0`, because the Halloween tokens start at level 1. Light `#eff2f5 #f0db3d #ffd642 #f68c41 #1f2328`, dark `#151b23 #fac68f #c46212 #984b10 #e3d04f`. On the dark graph that is pale peach, orange, burnt orange, then yellow.

`palette: christmas` (CLI: `--palette christmas`) paints both SVGs in pine green and red. Level 0 again keeps `--contribution-default-bgColor-0`, so empty cells stay the neutral GitHub background and the graph stays readable. Levels 1 and 2 are pine, a step darker on the light SVG and a step brighter on the dark SVG. Levels 3 and 4 are cranberry on the light SVG, a step darker, and true red on the dark SVG, a step brighter (`#b00000` then `#ff0000`). Light `#eff2f5 #a9d082 #529732 #d0123c #7c1024`, dark `#151b23 #234d22 #4d7c28 #b00000 #ff0000`.

`palette: auto` (CLI: `--palette auto`) uses the Halloween colors on 31 October UTC, the Christmas colors on 24, 25, and 26 December UTC, and the default green palette on every other UTC date. The check is that calendar day in UTC, not the runner's local zone. Omit `palette` to keep the green graph on every day, including those holidays.

## Develop

No third-party packages. Python 3.10 or newer.

```bash
python3 -m unittest test_brickfall.py
python3 generate.py --input sample/contributions.json --out dist
python3 generate.py --username KenYanL --token "$GITHUB_TOKEN" --out dist
python3 generate.py --input sample/contributions.json --out dist --palette halloween
python3 generate.py --input sample/contributions.json --out dist --palette christmas
python3 generate.py --input sample/contributions.json --out dist --palette auto
```

`--palette` is the same choice as the action's `palette` input. `auto` reads the UTC date when the process starts. Halloween is 31 October. Christmas is 24, 25, and 26 December.

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
