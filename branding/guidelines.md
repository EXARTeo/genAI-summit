# Brand guidelines

Sources: [`source/logo-a-plus-c.pdf`](source/logo-a-plus-c.pdf) (logo lockups) and
[`source/color-palette.pdf`](source/color-palette.pdf) (palette and rules). Values live in
[`brand.json`](brand.json); this page says how to use them.

## Name

| | |
| --- | --- |
| Brand name | **Mnamon** (`brand.json` → `name`) |
| Meaning | Greek *μνάμων*, "the one who remembers": the agent keeps the memory of every audit and every lesson |
| Product | **AI Act Governance Copilot** (`brand.json` → `product`); short form *AI Act Copilot* where space is tight |
| How to write it | *Mnamon* in running text, capital M only; **MNAMON** only inside the logo wordmark. Never "MNAMON" in prose, never abbreviated |
| Tagline | "Agentic EU AI Act audits your engineers can trust, step by step." (`brand.json` → `tagline`) |
| Lex and Praxis | The two halves of the mark: **lex** (blue) is the law, **praxis** (terra) is the engineering work that tests against it |

## Voice

| We are | We are not |
| --- | --- |
| Precise: every claim cites its source | Vague or hand-wavy about the law |
| Calm and auditable | Alarmist about fines and risk |
| Honest about limits ("inconclusive", "not assessable by testing") | Overconfident or "AI magic" |
| Plain English for engineers and managers alike | Legalese or buzzwords |

## Colour

Use the semantic tokens from `brand.json`, never raw hex values. Every screen and slide must work in light and dark.

| Role | Light | Dark | Palette name | Use |
| --- | --- | --- | --- | --- |
| `background` | `#F4F1EA` | `#13171F` | parch / ink | Page and slide background |
| `surface` | `#FBF9F4` | `#1D2330` | parch (lifted) / ink-2 | Cards, panels |
| `surface_muted` | `#E9E3D6` | `#252C3B` | parch-2 / ink-2 (lifted) | Wells, inputs, table headers |
| `text` | `#1B2029` | `#EDE8DC` | head-dark / on-dark | Main text |
| `muted` | `#4A4F5A` | `#B9BFCB` | body-dark / body-on-dark | Secondary text, captions |
| `border` | `#DCD4C3` | `#323A4B` | (derived) | Dividers, outlines |
| `primary` | `#9E4A17` | `#D2773A` | terra-deep / terra | Calls to action, active state, key highlights |
| `primary_foreground` | `#FBF9F4` | `#13171F` | parch / ink | Text on `primary` |
| `accent` | `#2F5F80` | `#7FB0D1` | lex-deep / lex | Links to the law, secondary highlights |
| `ring` | `#B85A20` | `#D2773A` | terra-mark / terra | Focus rings |
| `info` | `#2F5F80` | `#7FB0D1` | lex-deep / lex | Informational states |
| `success` / `danger` | `#2E6B45` / `#A63228` | `#74C69D` / `#EE8A7E` | (added) | Verdicts only: supports compliance / gap |
| `warning` | `#8A5F00` | `#E5BE5C` | (added, ochre) | Human-in-the-loop only: approvals, needs review |
| `logo_lex` / `logo_terra` | `#2F5F80` / `#B85A20` | `#7FB0D1` / `#D2773A` | lex-deep, terra-mark / lex, terra | The logo mark only |

Rules from the palette sheet, kept everywhere:

- **On a terra background, text is ink.** In light mode the CTA uses terra-deep with parch text instead, because
  terra on parch is only 2.9:1.
- **Small terra text on parch uses terra-deep** (that is why light `primary` is terra-deep).
- **Lex (`#7FB0D1`) only on ink.** On light backgrounds use lex-deep.
- `primary` carries the brand: buttons, the active nav item, key numbers. Not large blocks of body text.
- `warning` is reserved for "a human must decide"; green and red are reserved for verdicts.
- Contrast meets WCAG AA in both themes: text and state colours at least 4.5:1 on their backgrounds, the focus ring
  and logo colours at least 3:1 (table of ratios in the CHANGELOG entry and `tests/test_branding.py`).

## Logo

- Use `logo.svg` / `logo-on-light.png` on light backgrounds and `logo-on-dark.svg` / `logo-on-dark.png` on dark
  ones. The deck builder and the frontend pick the right one automatically.
- The mark alone (`mark.svg`) is for tight spaces (sidebar rail, slide corners); the tiled `icon` is for app icons
  and favicons.
- Keep clear space around the logo equal to the stroke width ×2 (about a third of the mark's height).
- Minimum size: mark 20 px tall on screen; below 48 px use the solid (unstriped) favicon version.
- Do not stretch, recolour, rotate, re-order the colours (lex is always left, terra right), add effects or put the
  light-background version on ink.

## Typography

| Role | Font | Use |
| --- | --- | --- |
| Heading | `fonts.heading`: **EB Garamond** | The wordmark, page titles, slide headings |
| Body | `fonts.body`: **Inter** | Paragraphs, UI labels, bullets |
| Mono | `fonts.mono`: **JetBrains Mono** | Code, commands, IDs, hex values |
