# Presentations

Decks are written as YAML and built into `.pptx` files that take their name, colours, fonts and logo from [`branding/brand.json`](../branding/brand.json). Change the brand once and every deck picks up the change the next time it is built.

## Build

```bash
./scripts/build-decks.sh                 # every deck   (Windows: .\scripts\build-decks.ps1)
./scripts/build-decks.sh example         # one deck
./scripts/build-decks.sh example --theme dark
```

The output goes to `presentations/dist/<deck>.pptx`. That folder is git-ignored: decks are rebuilt from YAML, not committed.

## Make a new deck

1. Copy `decks/example/` to `decks/<your-deck>/`.
2. Edit `deck.yaml`. Put any images in the same folder.
3. Build it: `./scripts/build-decks.sh <your-deck>`.

## Deck file

```yaml
title: Deck title            # file metadata
theme: light                 # light | dark
footer: GenAI Summit 2026    # shown on content slides next to the brand name
slides:
  - layout: bullets
    title: Slide title
    bullets: [First point, Second point]
    notes: Optional speaker notes
```

## Layouts

| Layout | Required | Optional | Looks like |
| --- | --- | --- | --- |
| `title` | `title` | `subtitle`, `meta` | Full `primary` background, logo, big title |
| `section` | `title` | `subtitle` | `surface` background with an accent bar |
| `bullets` | `title`, `bullets` | | Title + bullet list. A bullet can be `{text, sub: [...]}` for sub-points |
| `two-column` | `title`, `left`, `right` | each column: `heading`, `bullets` | Two bullet columns |
| `image` | `title`, `image` | `caption` | Image scaled to fit (path relative to the deck folder) |
| `quote` | `quote` | `author` | Large italic quote |
| `closing` | `title` | `subtitle`, `meta` | Same as `title`, for the last slide |

Every slide also accepts `notes` (speaker notes).

## Notes

- Logos come from `branding/logo/`. Until those PNGs exist, a text wordmark with the product name is used.
- Fonts are not embedded. Install the brand fonts (see `branding/fonts/README.md`) on the machine you present from.
