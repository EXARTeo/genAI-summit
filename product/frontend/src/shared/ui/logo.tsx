// TODO(brand): replace placeholder logo (a minimal shield with a check). Keep branding/logo/logo.svg in sync.
import { cn } from '@/shared/lib/utils';

export const PRODUCT_NAME = 'AI Act Copilot'; // mirrors branding/brand.json → name

/** Placeholder mark: a solid teal rounded square with a white shield-check glyph. */
export function LogoMark({ className, title = PRODUCT_NAME }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn('size-7', className)} role="img" aria-label={title}>
      <rect width="32" height="32" rx="8" fill="rgb(var(--rgb-primary))" />
      <path
        d="M16 7.5 23 10v5.6c0 4.3-2.9 7.6-7 8.9-4.1-1.3-7-4.6-7-8.9V10l7-2.5Z"
        fill="none"
        stroke="rgb(var(--rgb-primary-foreground))"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path
        d="m12.8 16 2.3 2.3 4.2-4.6"
        fill="none"
        stroke="rgb(var(--rgb-primary-foreground))"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Logo({ collapsed, className }: { collapsed?: boolean; className?: string }) {
  return (
    <span className={cn('flex items-center gap-2', className)}>
      <LogoMark />
      {!collapsed && (
        <span className="text-sm font-semibold tracking-tight">
          AI Act <span className="font-normal text-muted">Copilot</span>
        </span>
      )}
    </span>
  );
}
