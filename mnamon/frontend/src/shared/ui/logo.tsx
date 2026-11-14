// The Mnamon logo (branding/logo/, source: branding/source/logo-a-plus-c.pdf). Drawn from scratch:
// it is our own brand mark, so no prebuilt component applies. Geometry mirrors
// branding/logo/make_svgs.py; colours come only from the logo tokens, so it follows the theme.
import { useId } from 'react';
import { cn } from '@/shared/lib/utils';

export const PRODUCT_NAME = 'Mnamon'; // mirrors branding/brand.json → name
export const PRODUCT_DESCRIPTOR = 'AI Act Copilot'; // short form of brand.json → product

/** One 70-unit stroke on a 75-unit grid: arch, U, arch (viewBox 520 × 365). */
const STROKE_PATH = 'M35 365V110A75 75 0 0 1 185 110V260A75 75 0 0 0 335 260V110A75 75 0 0 1 485 110V365';
/** Seven 35-unit bands with 20-unit gaps. */
const BANDS = [0, 55, 110, 165, 220, 275, 330];
const HALVES = [
  { key: 'lex', x: 0, color: 'rgb(var(--logo-lex))' },
  { key: 'terra', x: 260, color: 'rgb(var(--logo-terra))' },
] as const;

/**
 * The mark: lex (left) and terra (right), fading to 45% at the bottom. `solid` drops the
 * stripes, which blur away below ~24 px (favicon-sized uses).
 */
export function LogoMark({
  className,
  title = PRODUCT_NAME,
  solid = false,
}: {
  className?: string;
  title?: string;
  solid?: boolean;
}) {
  const id = useId().replace(/:/g, '');
  return (
    // Square viewBox so the mark centres in square icon boxes.
    <svg viewBox="0 -77.5 520 520" className={cn('size-7', className)} role="img" aria-label={title}>
      <defs>
        {HALVES.map((h) => (
          <linearGradient
            key={h.key}
            id={`${id}-g-${h.key}`}
            x1="0"
            y1="0"
            x2="0"
            y2="365"
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0" style={{ stopColor: h.color }} />
            <stop offset="1" style={{ stopColor: h.color, stopOpacity: 0.45 }} />
          </linearGradient>
        ))}
        {HALVES.map((h) => (
          <clipPath key={h.key} id={`${id}-c-${h.key}`}>
            {solid ? (
              <rect x={h.x} y="0" width="260" height="365" />
            ) : (
              BANDS.map((y) => <rect key={y} x={h.x} y={y} width="260" height="35" />)
            )}
          </clipPath>
        ))}
      </defs>
      {HALVES.map((h) => (
        <path
          key={h.key}
          d={STROKE_PATH}
          fill="none"
          stroke={`url(#${id}-g-${h.key})`}
          strokeWidth="70"
          clipPath={`url(#${id}-c-${h.key})`}
        />
      ))}
    </svg>
  );
}

/** The MNAMON wordmark: EB Garamond (brand heading font), wide tracking, as in the lockup. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span
      className={cn('font-heading text-lg font-medium uppercase leading-none tracking-[0.19em]', className)}
    >
      {PRODUCT_NAME}
    </span>
  );
}

export function Logo({ collapsed, className }: { collapsed?: boolean; className?: string }) {
  return (
    <span className={cn('flex items-center gap-2', className)}>
      <LogoMark />
      {!collapsed && <Wordmark />}
    </span>
  );
}
