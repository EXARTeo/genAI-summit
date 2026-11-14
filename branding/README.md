# Branding

The single source of truth for the product's identity. Everything else (the frontend, the presentations, the docs) reads from here instead of copying colours or names.

> **Status:** placeholder values. Replace `name`, `tagline`, colours, fonts and logos once the brand is decided.

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

## Generate CSS variables

```bash
uv run python branding/export_tokens.py      # writes branding/dist/tokens.css
```

The CSS defines `--color-*` and `--font-*` variables on `:root`, switches to dark values under `prefers-color-scheme: dark`, and lets `data-theme="light"` / `data-theme="dark"` on `<html>` override the system setting.

## Changing the brand

1. Edit `brand.json` (and drop the new logo files into `logo/`).
2. Run `./scripts/build-decks.sh` (or `.ps1`) to rebuild every deck with the new look.
3. Run `uv run python branding/export_tokens.py` and copy `dist/tokens.css` into the frontend.
