import { cva, type VariantProps } from 'class-variance-authority';
import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';

export const badgeVariants = cva(
  'inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-md border px-1.5 text-2xs font-medium [&_svg]:size-3',
  {
    variants: {
      tone: {
        neutral: 'border-border bg-surface-muted/60 text-muted',
        primary: 'border-primary/20 bg-primary/10 text-primary',
        accent: 'border-accent/20 bg-accent/10 text-accent',
        success: 'border-success/20 bg-success/10 text-success',
        warning: 'border-warning/25 bg-warning/10 text-warning',
        danger: 'border-danger/20 bg-danger/10 text-danger',
        info: 'border-border bg-surface-muted/60 text-info',
        solid: 'border-transparent bg-primary text-primary-foreground',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
);

export type BadgeTone = NonNullable<VariantProps<typeof badgeVariants>['tone']>;

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {
  icon?: ReactNode;
}

export function Badge({ className, tone, icon, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ tone }), className)} {...props}>
      {icon}
      {children}
    </span>
  );
}

/**
 * Status vocabulary shared by the whole UI. Unknown statuses fall back to `neutral`.
 * Covers system, audit, step, artifact and approval states.
 */
const STATUS_TONE: Record<string, BadgeTone> = {
  // generic
  active: 'success',
  done: 'success',
  completed: 'success',
  approved: 'success',
  passed: 'success',
  supports_compliance: 'success',
  running: 'primary',
  in_progress: 'primary',
  active_step: 'primary',
  queued: 'neutral',
  pending: 'neutral',
  draft: 'neutral',
  proposed: 'info',
  pilot: 'info',
  production: 'accent',
  needs_approval: 'warning',
  awaiting_approval: 'warning',
  changes_requested: 'warning',
  inconclusive: 'warning',
  stale: 'warning',
  blocked: 'danger',
  failed: 'danger',
  rejected: 'danger',
  indicates_gap: 'danger',
  error: 'danger',
  superseded: 'neutral',
  retired: 'neutral',
  not_assessable_by_testing: 'neutral',
};

const PULSING = new Set(['running', 'in_progress', 'needs_approval', 'awaiting_approval']);

export interface StatusPillProps extends HTMLAttributes<HTMLSpanElement> {
  status: string;
  /** Override the label (defaults to the status, humanised). */
  label?: ReactNode;
  tone?: BadgeTone;
}

export function StatusPill({ status, label, tone, className, ...props }: StatusPillProps) {
  const key = status.toLowerCase();
  const t = tone ?? STATUS_TONE[key] ?? 'neutral';
  const live = PULSING.has(key);
  return (
    <span className={cn(badgeVariants({ tone: t }), 'rounded-full px-2', className)} {...props}>
      <span className="relative flex size-1.5">
        {live && <span className="absolute -inset-0.5 animate-ping rounded-full bg-current opacity-40" />}
        <span className="relative size-1.5 rounded-full bg-current" />
      </span>
      {label ?? key.replace(/_/g, ' ')}
    </span>
  );
}
