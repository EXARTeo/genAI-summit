/**
 * The main agent on the agent map and the plan panel: the Mnamon mark in a round tile, with the
 * app's thin working arc (`.agent-orb`) turning round it while something runs. Stands in for
 * magenticx's `Orb` (a WebGL blob), which is decorative and has no place in this design system.
 */
import { cn } from '@/shared/lib/utils';
import { LogoMark } from '@/shared/ui';

export function AgentAvatar({
  size = 40,
  working = false,
  className,
}: {
  size?: number;
  working?: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn('relative grid shrink-0 place-items-center', className)}
      style={{ width: size, height: size }}
    >
      <span className="absolute inset-0 rounded-full border border-border/70 bg-surface-sunken" />
      {working ? <span className="agent-orb absolute -inset-[3px]" /> : null}
      <LogoMark solid title="" className="relative" />
    </span>
  );
}
