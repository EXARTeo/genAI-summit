// TODO(brand): replace placeholder logo (shield + check mark). Keep branding/logo/logo.svg in sync.
import { cn } from '@/shared/lib/utils';

export const PRODUCT_NAME = 'AI Act Copilot'; // mirrors branding/brand.json → name

export function LogoMark({ className, title = PRODUCT_NAME }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={cn('size-8', className)} role="img" aria-label={title}>
      <defs>
        <linearGradient id="logo-grad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="rgb(var(--rgb-primary))" />
          <stop offset="1" stopColor="rgb(var(--rgb-accent))" />
        </linearGradient>
      </defs>
      <path
        d="M32 4 54 12v18c0 14.5-9.4 25.6-22 30C19.4 55.6 10 44.5 10 30V12L32 4Z"
        fill="url(#logo-grad)"
      />
      <path
        d="m22 32 7 7 13-15"
        fill="none"
        stroke="white"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Logo({ collapsed, className }: { collapsed?: boolean; className?: string }) {
  return (
    <span className={cn('flex items-center gap-2.5', className)}>
      <LogoMark />
      {!collapsed && (
        <span className="flex flex-col leading-none">
          <span className="text-[15px] font-semibold tracking-tight">AI Act</span>
          <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-[11px] font-semibold uppercase tracking-[0.18em] text-transparent">
            Copilot
          </span>
        </span>
      )}
    </span>
  );
}
