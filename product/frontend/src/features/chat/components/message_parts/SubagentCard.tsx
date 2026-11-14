/**
 * A delegated sub-agent (magenticx `message_parts/SubagentContainer.tsx` + `SubagentTreeCard`):
 * its type and task, a live status, and its own thinking and answer folded inside. A teal hairline
 * slides across the top while it works (our `GlowCard` motion).
 */
import { Bot, ChevronRight } from 'lucide-react';
import { useEffect, useState } from 'react';
import { cn } from '@/shared/lib/utils';
import { StatusPill } from '@/shared/ui';
import type { SubagentBlock } from '../../lib/timeline';
import { ChatMarkdown } from './ChatMarkdown';
import { ThinkingBlock } from './ThinkingBlock';

const STATUS: Record<SubagentBlock['status'], { label: string; pill: string }> = {
  pending: { label: 'Queued', pill: 'pending' },
  running: { label: 'Working', pill: 'running' },
  awaiting_approval: { label: 'Needs approval', pill: 'needs_approval' },
  done: { label: 'Done', pill: 'completed' },
  failed: { label: 'Failed', pill: 'failed' },
  cancelled: { label: 'Stopped', pill: 'cancelled' },
};

function took(block: SubagentBlock) {
  if (!block.startedAt || !block.endedAt) return null;
  const s = Math.round((block.endedAt - block.startedAt) / 1000);
  return `${s} s`;
}

export function SubagentCard({ block, live }: { block: SubagentBlock; live: boolean }) {
  const working = block.status === 'running' || block.status === 'awaiting_approval';
  const [open, setOpen] = useState(working);
  useEffect(() => setOpen(working), [working]);
  const status = STATUS[block.status];
  const tools = block.blocks.reduce(
    (n, b) => n + (b.kind === 'thinking' ? b.items.filter((i) => i.kind === 'tool').length : 0),
    0,
  );
  if (!block.spawned && block.status === 'pending' && !live) return null;
  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-xl border border-border bg-surface',
        working && 'glow-border',
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left"
      >
        <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
          <Bot className="size-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 text-sm font-medium">
            {block.label ?? 'Sub-agent'}
            <span className="font-mono text-2xs font-normal text-muted">{block.type}</span>
          </span>
          {block.description && (
            <span className="block truncate text-xs text-muted">{block.description}</span>
          )}
        </span>
        <span className="flex shrink-0 items-center gap-2 text-2xs text-muted">
          {tools > 0 && (
            <span>
              {tools} tool{tools > 1 ? 's' : ''}
            </span>
          )}
          {took(block) && <span className="num">{took(block)}</span>}
          <StatusPill status={status.pill} label={status.label} />
          <ChevronRight className={cn('size-3.5 transition-transform', open && 'rotate-90')} />
        </span>
      </button>
      {open && (
        <div className="space-y-2.5 border-t border-border px-3 py-2.5">
          {block.blocks.length === 0 && (
            <p className="text-xs text-muted">Waiting for the sub-agent to start…</p>
          )}
          {block.blocks.map((b) =>
            b.kind === 'thinking' ? (
              <ThinkingBlock key={b.id} block={b} live={live && working} />
            ) : (
              <ChatMarkdown key={b.id} text={b.text} className="text-[13px]" />
            ),
          )}
        </div>
      )}
    </div>
  );
}
