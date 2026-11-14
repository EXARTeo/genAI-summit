/**
 * The chain of thought's building blocks (magenticx `shared/ui/ai-elements/chain-of-thought.tsx`
 * step + `Collapse.tsx`): one step on the vertical guide line (icon, label, body) and the
 * height + fade collapse every run block opens with. Instant under reduced motion
 * (`MotionConfig reducedMotion="user"` in main.tsx).
 */
import { AnimatePresence, motion } from 'framer-motion';
import { Dot, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { collapse } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';

export function Collapse({
  open,
  className,
  children,
}: {
  open: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <AnimatePresence initial={false}>
      {open ? (
        <motion.div
          variants={collapse}
          initial="initial"
          animate="animate"
          exit="exit"
          className={cn('overflow-hidden', className)}
        >
          {children}
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

export function CoTStep({
  icon: Icon = Dot,
  iconClassName,
  label,
  hideConnector = false,
  active = false,
  className,
  children,
}: {
  icon?: LucideIcon | ((props: { className?: string }) => ReactNode);
  iconClassName?: string;
  label?: ReactNode;
  hideConnector?: boolean;
  /** The step is still being written: full-contrast text. */
  active?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div className={cn('flex gap-2 text-sm', active ? 'text-text' : 'text-muted', className)}>
      <div className="relative mt-0.5 shrink-0">
        <Icon className={cn('size-4', iconClassName)} />
        {!hideConnector && (
          // Starts under the icon and overshoots the row to bridge the gap to the next step.
          <div aria-hidden className="absolute -bottom-5 left-1/2 top-5 -mx-px w-px bg-border" />
        )}
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        {label != null && label !== '' && <div>{label}</div>}
        {children}
      </div>
    </div>
  );
}
