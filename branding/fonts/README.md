# Fonts

The fonts named in `brand.json` → `fonts`. Fonts are **not** embedded in `.pptx` files, so anyone presenting a deck needs them installed. Otherwise PowerPoint swaps in a default font.

| Role | Font | Licence | Download |
| --- | --- | --- | --- |
| Heading (and the MNAMON wordmark) | EB Garamond | SIL OFL 1.1 | <https://fonts.google.com/specimen/EB+Garamond> |
| Body | Inter | SIL OFL 1.1 | <https://fonts.google.com/specimen/Inter> |
| Mono | JetBrains Mono | SIL OFL 1.1 | <https://fonts.google.com/specimen/JetBrains+Mono> |

The frontend bundles all three through `@fontsource-variable/*` packages, so the web app needs nothing installed.

If you change a font, update this table and commit the font's licence file here (font files themselves are optional).
