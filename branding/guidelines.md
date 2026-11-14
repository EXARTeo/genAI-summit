# Brand guidelines

> Draft. Fill in each section once the brand is decided.

## Name

| | |
| --- | --- |
| Product name | _tbd_ (in `brand.json` → `name`) |
| How to write it | _e.g. always one word, capital first letter, never abbreviated_ |
| Tagline | _tbd_ (in `brand.json` → `tagline`) |

## Voice

| We are | We are not |
| --- | --- |
| _e.g. clear_ | _e.g. jargon-heavy_ |
| _e.g. confident_ | _e.g. hype-driven_ |

## Colour

- Use the semantic tokens from `brand.json`, never raw hex values.
- `primary` carries the brand. Use it for title slides, main buttons and key highlights, not large blocks of body text.
- `accent` is for small touches: bars, bullet markers, links.
- Every screen and slide must work in both light and dark themes.
- Text contrast must meet WCAG AA (4.5:1 for body text).

## Logo

- Use `logo-on-light` on light backgrounds and `logo-on-dark` on dark ones. The deck builder picks the right one automatically.
- Keep clear space around the logo equal to the height of its icon.
- Do not stretch, recolour, rotate or add effects.

## Typography

| Role | Font | Use |
| --- | --- | --- |
| Heading | `fonts.heading` | Titles, slide headings |
| Body | `fonts.body` | Paragraphs, bullets |
| Mono | `fonts.mono` | Code, commands, IDs |
