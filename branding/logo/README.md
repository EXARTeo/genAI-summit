# Logo files

The Mnamon logo: the **mark** (one striped stroke drawn as arch, U, arch, lex blue on the left and terra on the
right, fading towards the bottom) and the **MNAMON** wordmark (EB Garamond Medium, wide tracking). Taken from
[`../source/logo-a-plus-c.pdf`](../source/logo-a-plus-c.pdf) ("A + C, without dot").

| File | Use |
| --- | --- |
| `logo.svg` | Master lockup (mark + wordmark) for light backgrounds: lex-deep, terra-mark, ink text |
| `logo-on-dark.svg` | Master lockup for dark backgrounds: lex, terra, on-dark text |
| `mark.svg` / `mark-on-dark.svg` | The mark alone, for light / dark backgrounds |
| `logo-on-light.png` / `logo-on-dark.png` | 2000 px wide, transparent: decks, docs, anywhere SVG is not supported |
| `icon.svg` / `icon.png` | App icon: the striped mark on an ink rounded tile (`icon.png` is 512×512) |
| `apple-touch-icon.png` | 180×180 copy of the icon for iOS home screens |
| `favicon.svg` / `favicon.ico` | Favicon: the mark as a **solid** stroke (stripes vanish below 48 px) on the ink tile; ICO holds 16, 32, 48 px |
| `make_svgs.py` | Generates every SVG above |

The frontend copies `favicon.svg`, `favicon.ico` and `apple-touch-icon.png` into `mnamon/frontend/public/`, and
draws the mark inline in `mnamon/frontend/src/shared/ui/logo.tsx` from the `logo_lex` / `logo_terra` tokens,
so it follows the theme.

## How the files were made

The source PDF holds only a raster image, so nothing could be extracted as vectors. Instead:

1. The mark was measured on the 3600×2040 raster: one 70-unit stroke on a 75-unit grid (centre lines at
   x = 35, 185, 335, 485; arches centred at y = 110, the U at y = 260), seven 35-unit bands with 20-unit gaps,
   split at x = 260, opacity fading from 100% to 45% top to bottom. The wordmark is the real EB Garamond Medium
   outlines, sized and tracked to match the sheet.
2. `make_svgs.py` writes the SVGs (needs fonttools and the EB Garamond woff2 from `@fontsource/eb-garamond`;
   usage in its docstring).
3. The PNGs were rendered from the SVGs with Playwright's Chromium (transparent background); `favicon.ico` and
   `apple-touch-icon.png` were downscaled from 256/512 px renders with Pillow.

To change the logo, edit `make_svgs.py`, re-run it and re-render the PNGs. Never edit the PNGs by hand.
