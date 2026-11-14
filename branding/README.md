# Branding

The single source of truth for the product's identity. Everything else (the frontend, the presentations, the docs) reads from here instead of copying colours or names.

> **Status:** working brand. `name` is **AI Act Copilot** (TODO: confirm or rename) and the palette is an
> "AI governance / trust" look (ink/indigo base, teal accent, amber for human approvals).
>
> **TODO(brand): replace placeholder logo.** `logo/logo.svg` (shield + check) is a placeholder; the frontend
> copies it in `product/frontend/public/favicon.svg` and `product/frontend/src/shared/ui/logo.tsx`. The PNGs
> (`logo-on-light.png`, `logo-on-dark.png`, `icon.png`) do not exist yet, so decks show a text wordmark.

## Files

| Path | What it is |
| --- | --- |
| [`brand.json`](brand.json) | Name, tagline, colour tokens (light + dark), fonts and logo paths |
| [`guidelines.md`](guidelines.md) | How to use the brand: voice, colour roles, logo rules |
| `logo/` | Logo files (see [logo/README.md](logo/README.md)) |
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

## Generate CSS variables

```bash
uv run python branding/export_tokens.py      # writes branding/dist/tokens.css
```

The CSS defines `--color-*` and `--font-*` variables on `:root`, switches to dark values under `prefers-color-scheme: dark`, and lets `data-theme="light"` / `data-theme="dark"` on `<html>` override the system setting.

## Changing the brand

1. Edit `brand.json` (and drop the new logo files into `logo/`).
2. Run `./scripts/build-decks.sh` (or `.ps1`) to rebuild every deck with the new look.
3. Run `uv run python branding/export_tokens.py --frontend` (or `npm run tokens` in `product/frontend/`): it
   writes `product/frontend/src/styles/theme/tokens.css`, which Tailwind reads (`--rgb-*` channels allow
   opacity like `bg-primary/10`). `tests/test_branding.py` fails when that file is stale.

That second command is all the frontend needs: every colour in the app (light + dark) derives from
`tokens.css` through `src/styles/theme/semantic.css` → `shape.css` → `components.css`, and no component
hard-codes a colour. Radii, shadows and component looks are not brand keys; change them in those files (see
"Theming" in [docs/services/frontend.md](../docs/services/frontend.md)). Optional extra colour keys:
`success_foreground`, `danger_foreground`, `info_foreground`, `chart_1`..`chart_5` (white text and
primary/info/warning/success/danger series otherwise).
