/**
 * Shared styling recipes: repeated class strings and colour helpers.
 *
 * Recipes are plain strings of real Tailwind utilities (not custom CSS classes), so
 * `cn()` / tailwind-merge can still de-duplicate them against a component's own
 * classes. Interpolate them; do not wrap them in a class of their own.
 * Every colour comes from the theme vars in src/styles/theme (see docs/services/frontend.md, "Theming").
 */

/** Semantic colour roles defined in src/styles/theme/semantic.css (as "R G B" channels). */
export type ColorRole =
  | 'background'
  | 'foreground'
  | 'surface'
  | 'surface-raised'
  | 'surface-sunken'
  | 'muted-foreground'
  | 'border'
  | 'ring'
  | 'primary'
  | 'primary-foreground'
  | 'accent'
  | 'accent-foreground'
  | 'success'
  | 'warning'
  | 'danger'
  | 'info'
  | 'chart-1'
  | 'chart-2'
  | 'chart-3'
  | 'chart-4'
  | 'chart-5';

/** A CSS colour for inline styles / SVG / charts: `color('primary', 0.2)` -> `rgb(var(--primary) / 0.2)`. */
export function color(role: ColorRole, alpha?: number): string {
  return alpha === undefined ? `rgb(var(--${role}))` : `rgb(var(--${role}) / ${alpha})`;
}

/** Chart series colours, assigned by index (wraps after 5). */
export const CHART_SERIES = [1, 2, 3, 4, 5].map((i) => color(`chart-${i}` as ColorRole));

/** Neutral hover / press fill for icon buttons, menu triggers and rail rows. */
export const INTERACTIVE_SURFACE = 'hover:bg-hover active:bg-hover-strong focus-visible:bg-hover-strong';

/** Same, without the focus-visible fill: for controls that own their focus ring. */
export const INTERACTIVE_SURFACE_QUIET = 'hover:bg-hover active:bg-hover-strong';

/** A raised card sitting on the app frame (the sidebar's search action). */
export const RAISED_ON_FRAME =
  'border-border/70 bg-shell-card shadow-sm hover:bg-shell-card hover:shadow-card dark:border-border';
