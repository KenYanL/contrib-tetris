# contrib-tetris

Contribution Brickfall (formerly Contribution Tetris) is a reusable GitHub Action that draws a contribution graph as falling Tetris bricks with LEGO studs. Pieces drop in and lock on the days they belong to, so the resting frame is the real calendar. Light and dark are separate animated SVGs, pure SVG and CSS, about 50KB each, with no extra packages.

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

### Outputs

| Output | Description |
| --- | --- |
| `svg_light_path` | Path of the light SVG that was written. |
| `svg_dark_path` | Path of the dark SVG that was written. |

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
