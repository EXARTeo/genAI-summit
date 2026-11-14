/**
 * One tool step (magenticx `message_parts/ToolCallViews.tsx` + `SourceCards.tsx`): name, state,
 * duration, its approval chip, and a collapsible body with the arguments and the result. A
 * search step that returned sources shows them as link chips.
 */
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  Wrench,
} from 'lucide-react';
import { useState } from 'react';
import { cn } from '@/shared/lib/utils';
import { formatArgs, humanizeToolName } from '../../lib/hitl';
import type { Source, ToolStep } from '../../lib/timeline';

function prettyJson(text: string): string {
  try {
    return formatArgs(JSON.parse(text));
  } catch {
    return text;
  }
}

function duration(start?: number, end?: number): string | null {
  if (!start || !end || end < start) return null;
  const s = (end - start) / 1000;
  return s < 1 ? `${Math.round(s * 1000)} ms` : `${s.toFixed(1)} s`;
}

export function SourceChips({ sources }: { sources: Source[] }) {
  return (
    <ul aria-label="Sources" className="flex flex-wrap gap-1.5">
      {sources.map((s) => {
        let host = s.url;
        try {
          host = new URL(s.url).hostname.replace(/^www\./, '');
        } catch {
          /* keep the url */
        }
        return (
          <li key={s.id}>
            <a
              href={s.url}
              target="_blank"
              rel="noreferrer noopener"
              title={`${s.title ?? host}\n${host}`}
              className="inline-flex max-w-[16rem] items-center gap-1.5 rounded-md border border-border bg-surface px-2 py-1 text-2xs text-muted transition-colors hover:border-primary/40 hover:text-text"
            >
              <span className="grid size-3.5 shrink-0 place-items-center rounded-sm bg-surface-muted text-[9px] font-semibold uppercase">
                {host.charAt(0)}
              </span>
              <span className="truncate">{s.title ?? host}</span>
            </a>
          </li>
        );
      })}
    </ul>
  );
}

function ApprovalChip({ status }: { status: 'pending' | 'approved' | 'rejected' }) {
  if (status === 'pending')
    return (
      <span className="approval-pulse inline-flex items-center gap-1 rounded-full bg-warning/15 px-1.5 py-px text-2xs font-medium text-warning">
        <ShieldAlert className="size-3" /> Needs approval
      </span>
    );
  if (status === 'approved')
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-1.5 py-px text-2xs text-success">
        <ShieldCheck className="size-3" /> Approved
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-danger/10 px-1.5 py-px text-2xs text-danger">
      <ShieldX className="size-3" /> Rejected
    </span>
  );
}

export function ToolCallView({ tool }: { tool: ToolStep }) {
  const [open, setOpen] = useState(false);
  const running = tool.state === 'input-streaming' || tool.state === 'input-available';
  const waiting = tool.approval?.status === 'pending';
  const failed = tool.state === 'output-error';
  const took = duration(tool.startedAt, tool.endedAt);
  const args = prettyJson(tool.argsText);
  return (
    <div className="rounded-lg border border-border bg-surface">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs"
      >
        <span
          className={cn(
            'grid size-5 shrink-0 place-items-center rounded-md',
            failed
              ? 'bg-danger/10 text-danger'
              : waiting
                ? 'bg-warning/15 text-warning'
                : 'bg-surface-muted text-muted',
          )}
        >
          {running && !waiting ? (
            <Loader2 className="size-3 animate-spin" />
          ) : failed ? (
            <AlertTriangle className="size-3" />
          ) : waiting ? (
            <ShieldAlert className="size-3" />
          ) : tool.state === 'output-available' ? (
            <Check className="size-3" />
          ) : (
            <Wrench className="size-3" />
          )}
        </span>
        <span className={cn('font-medium', running && !waiting && 'text-shimmer')}>
          {humanizeToolName(tool.name)}
        </span>
        <span className="truncate font-mono text-2xs text-muted">{tool.name}</span>
        <span className="ml-auto flex shrink-0 items-center gap-2">
          {tool.approval && <ApprovalChip status={tool.approval.status} />}
          {took && <span className="num text-2xs text-muted">{took}</span>}
          <ChevronRight className={cn('size-3.5 text-muted transition-transform', open && 'rotate-90')} />
        </span>
      </button>
      {tool.sources?.length ? (
        <div className="px-2.5 pb-2">
          <SourceChips sources={tool.sources} />
        </div>
      ) : null}
      {open && (
        <div className="space-y-2 border-t border-border px-2.5 py-2">
          {args && (
            <div>
              <div className="mb-1 text-2xs font-medium text-muted">Arguments</div>
              <pre className="max-h-48 overflow-auto rounded-md bg-surface-muted p-2 font-mono text-2xs leading-relaxed">
                {args}
              </pre>
            </div>
          )}
          {tool.result !== undefined && (
            <div>
              <div className="mb-1 text-2xs font-medium text-muted">
                Result{tool.resultTruncated ? ' (truncated)' : ''}
              </div>
              <pre
                className={cn(
                  'max-h-60 overflow-auto whitespace-pre-wrap rounded-md bg-surface-muted p-2 font-mono text-2xs leading-relaxed',
                  failed && 'text-danger',
                )}
              >
                {prettyJson(tool.result) || '(empty)'}
              </pre>
            </div>
          )}
          {tool.approval?.reason && <p className="text-2xs text-muted">Reviewer: {tool.approval.reason}</p>}
        </div>
      )}
    </div>
  );
}
