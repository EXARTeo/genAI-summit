import { forwardRef, type HTMLAttributes } from 'react';
import { cn } from '@/shared/lib/utils';

export interface GlowCardProps extends HTMLAttributes<HTMLDivElement> {
  /** Animate the gradient border (default true). Use for AI-produced or live content. */
  active?: boolean;
}

/** A card with an AI-style animated indigo→teal gradient border. */
export const GlowCard = forwardRef<HTMLDivElement, GlowCardProps>(
  ({ className, active = true, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'rounded-xl bg-surface text-text shadow-card',
        active ? 'glow-border shadow-glow' : 'border border-border',
        className,
      )}
      {...props}
    />
  ),
);
GlowCard.displayName = 'GlowCard';
