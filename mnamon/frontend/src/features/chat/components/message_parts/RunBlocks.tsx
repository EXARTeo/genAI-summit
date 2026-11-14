/**
 * Smaller run blocks (magenticx `ArtifactCard`, `TaskRefBlockView`, `TaskSettledMarker`,
 * `plan/PlanChecklist`): a presented artifact (opens the generated attachment it maps to), a
 * background task started / finished, and the agent's plan.
 */
import { Check, CircleDashed, FileOutput, ListTodo, Loader2, Workflow } from 'lucide-react';
import { cn } from '@/shared/lib/utils';
import type { ArtifactBlock, PlanItem, TaskRefBlock, TaskSettledBlock } from '../../lib/timeline';
import type { AttachmentOut } from '../../lib/types';
import { useChatUi } from '../chatContext';

export function ArtifactCard({
  block,
  attachment,
  messageId,
}: {
  block: ArtifactBlock;
  attachment?: AttachmentOut;
  messageId: string;
}) {
  const { openPreview } = useChatUi();
  const ready = Boolean(attachment);
  return (
    <button
      type="button"
      disabled={!ready}
      onClick={() => attachment && openPreview({ kind: 'sent', attachment, messageId })}
      className="hover-lift flex w-full max-w-md items-center gap-3 rounded-xl border border-border bg-surface p-3 text-left disabled:cursor-default"
    >
      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
        <FileOutput className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{block.title ?? block.filename}</span>
        {block.summary && <span className="line-clamp-2 text-xs text-muted">{block.summary}</span>}
        <span className="mt-0.5 block truncate font-mono text-2xs text-muted">{block.path}</span>
      </span>
      <span className="shrink-0 text-2xs text-muted">{ready ? 'Open' : 'Saving…'}</span>
    </button>
  );
}

export function TaskRefRow({ block }: { block: TaskRefBlock }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-dashed border-border px-2.5 py-1.5 text-xs">
      <Workflow className="size-3.5 text-primary" />
      <span className="font-medium">
        {block.action === 'update' ? 'Updated task' : 'Started background task'}
      </span>
      <span className="truncate text-muted">{block.name}</span>
      {block.description && (
        <span className="hidden truncate text-muted sm:inline">· {block.description}</span>
      )}
    </div>
  );
}

export function TaskSettledRow({ block }: { block: TaskSettledBlock }) {
  const ok = block.status === 'success' || block.status === 'completed';
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <Check className={cn('size-3.5', ok ? 'text-success' : 'text-danger')} />
      <span>
        {block.name} {ok ? 'finished' : block.status}
      </span>
    </div>
  );
}

export function PlanChecklist({ items }: { items: PlanItem[] }) {
  const done = items.filter((i) => i.status === 'completed').length;
  return (
    <div className="rounded-xl border border-border bg-surface p-3">
      <div className="mb-2 flex items-center gap-2 text-xs font-medium">
        <ListTodo className="size-3.5 text-primary" /> Plan
        <span className="num ml-auto text-2xs font-normal text-muted">
          {done}/{items.length}
        </span>
      </div>
      <ol className="space-y-1">
        {items.map((item, i) => (
          <li key={i} className="flex items-start gap-2 text-xs">
            {item.status === 'completed' ? (
              <Check className="mt-0.5 size-3.5 shrink-0 text-success" />
            ) : item.status === 'in_progress' ? (
              <Loader2 className="mt-0.5 size-3.5 shrink-0 animate-spin text-primary" />
            ) : (
              <CircleDashed className="mt-0.5 size-3.5 shrink-0 text-muted" />
            )}
            <span className={cn(item.status === 'completed' && 'text-muted line-through')}>
              {item.content}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
