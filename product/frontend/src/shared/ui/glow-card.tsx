import { forwardRef, type HTMLAttributes } from 'react';
import { cn } from '@/shared/lib/utils';

export interface GlowCardProps extends HTMLAttributes<HTMLDivElement> {
  /** Show the live hairline (default true). Use while an agent is working on this content. */
  active?: boolean;
}

/** A card for live agent content: a calm teal hairline slides across the top while `active`. */
export const GlowCard = forwardRef<HTMLDivElement, GlowCardProps>(
  ({ className, active = true, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'rounded-xl border bg-surface text-text',
        active ? 'glow-border border-primary/30' : 'border-border',
        className,
      )}
      {...props}
    />
  ),
);
GlowCard.displayName = 'GlowCard';
