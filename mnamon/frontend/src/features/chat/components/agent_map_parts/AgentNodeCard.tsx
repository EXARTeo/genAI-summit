/**
 * One sub-agent in the agent map (port of magenticx `agent_map/AgentNodeCard.tsx`): the inline
 * card's collapsed row in miniature (icon, name and type, its task on one line, the sub-agents it
 * delegated to, tool calls, time, status chip), with the inline card's working hairline along the
 * top edge (`glow-border`). Presentational: the tree around it owns the click and the keyboard.
 */
import { Bot, ChevronDown, ChevronRight, GitBranch, Wrench } from 'lucide-react';
import { cn } from '@/shared/lib/utils';
import { agentNodeDuration, type AgentMapNode } from '../../lib/agentMap';
import { SubagentStatusChip } from '../message_parts/SubagentStatusChip';

const normalizeName = (value: string) => value.toLowerCase().replace(/[-_\s]+/g, '');

export function AgentNodeCard({
  node,
  now,
  expanded,
  onToggle,
  className,
}: {
  node: AgentMapNode;
  now: number;
  /** Children shown under it in the tree; undefined when it cannot collapse. */
  expanded?: boolean;
  onToggle?: () => void;
  className?: string;
}) {
  const active = node.status === 'running';
  const duration = agentNodeDuration(node, now);
  const childCount = node.children.length;
  // "regulation-researcher" under "Regulation Researcher" says nothing new.
  const showType = Boolean(node.type && normalizeName(node.type) !== normalizeName(node.title));

  return (
    <div
      className={cn(
        'relative flex h-14 items-center gap-3 overflow-hidden rounded-2xl border bg-surface px-3 transition-[border-color,box-shadow] duration-200',
        'supports-[hover:hover]:group-hover/node:border-primary/40 supports-[hover:hover]:group-hover/node:shadow-card',
        active ? 'glow-border border-primary/30' : 'border-border/70',
        className,
      )}
    >
      <span
        className={cn(
          'grid size-8 shrink-0 place-items-center rounded-full transition-transform duration-300 ease-out motion-safe:supports-[hover:hover]:group-hover/node:scale-110',
          'bg-primary/10 text-primary',
        )}
      >
        <Bot className="size-4" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-2">
          <span className="min-w-0 truncate text-[13.5px] font-semibold text-text">{node.title}</span>
          {showType ? (
            <span className="hidden shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[9px] font-medium uppercase tracking-[0.16em] text-primary sm:inline">
              {node.type}
            </span>
          ) : null}
        </span>
        {node.task ? (
          <span className="block truncate text-xs leading-[1.15rem] text-muted">{node.task}</span>
        ) : null}
      </span>
      {childCount ? (
        onToggle ? (
          <button
            type="button"
            tabIndex={-1}
            onClick={(event) => {
              event.stopPropagation();
              onToggle();
            }}
            aria-label={`${expanded ? 'Hide' : 'Show'} the ${childCount} sub-agent${childCount === 1 ? '' : 's'} it delegated to`}
            className="num flex h-7 shrink-0 items-center gap-1 rounded-full border border-border/70 bg-background px-2 text-xs font-medium text-muted transition-colors supports-[hover:hover]:hover:border-primary/40 supports-[hover:hover]:hover:text-text"
          >
            <GitBranch className="size-3" aria-hidden />
            {childCount}
            <ChevronDown
              className={cn('size-3 transition-transform duration-200', !expanded && '-rotate-90')}
              aria-hidden
            />
          </button>
        ) : (
          <span
            className="num flex shrink-0 items-center gap-1 text-xs text-muted"
            title={`${childCount} nested sub-agent${childCount === 1 ? '' : 's'}`}
          >
            <GitBranch className="size-3" aria-hidden />
            {childCount}
          </span>
        )
      ) : null}
      {node.toolCount ? (
        <span
          className="num hidden shrink-0 items-center gap-1 text-xs text-muted sm:flex"
          title={`${node.toolCount} tool call${node.toolCount === 1 ? '' : 's'}`}
        >
          <Wrench className="size-3" aria-hidden />
          {node.toolCount}
        </span>
      ) : null}
      {duration ? <span className="num hidden shrink-0 text-xs text-muted sm:inline">{duration}</span> : null}
      {node.status ? <SubagentStatusChip status={node.status} compact /> : null}
      <ChevronRight
        aria-hidden
        className="hidden size-4 shrink-0 text-muted/70 transition-transform duration-200 motion-safe:supports-[hover:hover]:group-hover/node:translate-x-0.5 sm:block"
      />
    </div>
  );
}
