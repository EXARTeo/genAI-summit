# Branding

The single source of truth for the product's identity. Everything else (the frontend, the presentations, the docs) reads from here instead of copying colours or names.

> **Brand:** **Mnamon** (Greek *μνάμων*, "the one who remembers": the agent keeps the memory of every audit),
> the product is the *AI Act Governance Copilot*. Logo and palette come from the design sheets in
> [`source/`](source/) (`logo-a-plus-c.pdf`, `color-palette.pdf`): an ink/parchment base, **terra** (Praxis,
> calls to action) and **lex** (the law, second accent). See [guidelines.md](guidelines.md).

## Files

| Path | What it is |
| --- | --- |
| [`brand.json`](brand.json) | Name, product, tagline, colour tokens (light + dark), fonts and logo paths |
| [`guidelines.md`](guidelines.md) | How to use the brand: voice, colour roles, logo rules |
| `logo/` | Logo files (see [logo/README.md](logo/README.md)) |
| `source/` | The designer's sheets the brand is taken from (logo lockups, palette); read-only references |
| `fonts/` | Font licences and download links (see [fonts/README.md](fonts/README.md)) |
| [`export_tokens.py`](export_tokens.py) | Generates `dist/tokens.css` (CSS variables) from `brand.json` |

## Colour tokens

Colours are **semantic**: code and slides ask for `primary` or `muted`, never a raw hex value. Each token has a light and a dark value.

| Token | Used for |
| --- | --- |
| `background` | Page and slide background |
| `surface` | Cards, panels, section slides |
| `text` | Main text |
| `muted` | Secondary text, captions, footers |
| `border` | Dividers and outlines |
| `primary` | Brand colour: title slides, buttons, highlights |
| `primary_foreground` | Text on top of `primary` |
| `accent` | Small highlights: bars, bullets, links |
| `surface_muted` | Sunken areas: table headers, code, inputs at rest |
| `ring` | Focus rings |
| `accent_foreground` | Text on top of `accent` |
| `success`, `danger`, `info` | Semantic states (supports compliance, gap, info) |
| `warning`, `warning_foreground` | Human-in-the-loop: approvals, needs-review, inconclusive |
| `success_foreground`, `danger_foreground`, `info_foreground` | Text on top of the state colours |
| `logo_lex`, `logo_terra` | The two halves of the logo mark (lex-deep/terra-mark on light, lex/terra on dark) |

## Generate CSS variables

```bash
uv run python branding/export_tokens.py      # writes branding/dist/tokens.css
```

The CSS defines `--color-*` and `--font-*` variables on `:root`, switches to dark values under `prefers-color-scheme: dark`, and lets `data-theme="light"` / `data-theme="dark"` on `<html>` override the system setting.

## Changing the brand

1. Edit `brand.json` (and drop the new logo files into `logo/`).
2. Run `./scripts/build-decks.sh` (or `.ps1`) to rebuild every deck with the new look.
3. Run `uv run python branding/export_tokens.py --frontend` (or `npm run tokens` in `mnamon/frontend/`): it
   writes `mnamon/frontend/src/styles/theme/tokens.css`, which Tailwind reads (`--rgb-*` channels allow
   opacity like `bg-primary/10`). `tests/test_branding.py` fails when that file is stale.

That second command is all the frontend needs: every colour in the app (light + dark) derives from
`tokens.css` through `src/styles/theme/semantic.css` → `shape.css` → `components.css`, and no component
hard-codes a colour. Radii, shadows and component looks are not brand keys; change them in those files (see
"Theming" in [docs/services/frontend.md](../docs/services/frontend.md)). Optional extra colour keys:
`chart_1`..`chart_5` (primary/info/warning/success/danger series otherwise).
