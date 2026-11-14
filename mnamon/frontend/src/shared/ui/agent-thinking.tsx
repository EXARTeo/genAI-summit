import { AnimatePresence, motion } from 'framer-motion';
import type { ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';

export interface AgentThinkingProps {
  /** What the agent is doing now, e.g. "Planning tests for Art. 10(2)(f)". */
  label?: ReactNode;
  /** Optional secondary line (tool name, file). */
  detail?: ReactNode;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const ORB = { sm: 'size-3', md: 'size-4', lg: 'size-6' };

/** Thin spinner + shimmering label for a running agent step. */
export function AgentThinking({ label = 'Thinking', detail, size = 'md', className }: AgentThinkingProps) {
  return (
    <div role="status" aria-live="polite" className={cn('flex items-center gap-2', className)}>
      <span className={cn('relative shrink-0', ORB[size])}>
        <span className="agent-orb absolute inset-0" />
      </span>
      <div className="min-w-0">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={typeof label === 'string' ? label : undefined}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.2 }}
            className={cn('text-shimmer truncate font-medium', size === 'sm' ? 'text-xs' : 'text-sm')}
          >
            {label}
          </motion.div>
        </AnimatePresence>
        {detail && <div className="truncate font-mono text-xs text-muted">{detail}</div>}
      </div>
    </div>
  );
}
