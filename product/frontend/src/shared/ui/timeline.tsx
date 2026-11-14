import { motion } from 'framer-motion';
import type { ReactNode } from 'react';
import { formatDateTime, formatRelative } from '@/shared/lib/format';
import { listItem, staggerList } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';
import type { BadgeTone } from './badge';

export interface TimelineItem {
  id: string;
  title: ReactNode;
  description?: ReactNode;
  /** ISO timestamp. */
  at?: string;
  actor?: ReactNode;
  icon?: ReactNode;
  tone?: BadgeTone;
  /** Extra content (diff, code, links). */
  content?: ReactNode;
}

const DOT: Record<BadgeTone, string> = {
  neutral: 'bg-surface-muted text-muted border-border',
  primary: 'bg-primary/10 text-primary border-primary/30',
  accent: 'bg-accent/10 text-accent border-accent/30',
  success: 'bg-success/10 text-success border-success/30',
  warning: 'bg-warning/10 text-warning border-warning/30',
  danger: 'bg-danger/10 text-danger border-danger/30',
  info: 'bg-info/10 text-info border-info/30',
  solid: 'bg-primary text-primary-foreground border-primary',
};

/** Vertical activity feed (audit ledger, file events, agent actions). */
export function Timeline({ items, className }: { items: TimelineItem[]; className?: string }) {
  return (
    <motion.ol
      variants={staggerList()}
      initial="initial"
      animate="animate"
      className={cn('relative', className)}
    >
      {items.map((it, i) => (
        <motion.li key={it.id} variants={listItem} className="relative flex gap-3 pb-5 last:pb-0">
          {i < items.length - 1 && (
            <span aria-hidden className="absolute left-[13px] top-8 h-[calc(100%-2rem)] w-px bg-border" />
          )}
          <span
            className={cn(
              'grid size-7 shrink-0 place-items-center rounded-full border [&_svg]:size-3.5',
              DOT[it.tone ?? 'neutral'],
            )}
          >
            {it.icon ?? <span className="size-1.5 rounded-full bg-current" />}
          </span>
          <div className="min-w-0 flex-1 pt-0.5">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
              <div className="text-sm font-medium">{it.title}</div>
              {it.at && (
                <time dateTime={it.at} title={formatDateTime(it.at)} className="text-xs text-muted">
                  {formatRelative(it.at)}
                </time>
              )}
            </div>
            {(it.description || it.actor) && (
              <div className="mt-0.5 text-sm text-muted">
                {it.actor && <span className="font-medium text-text/80">{it.actor}</span>}
                {it.actor && it.description && ' · '}
                {it.description}
              </div>
            )}
            {it.content && <div className="mt-2">{it.content}</div>}
          </div>
        </motion.li>
      ))}
    </motion.ol>
  );
}
