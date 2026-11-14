/**
 * Smaller run blocks (magenticx `ArtifactCard`, `TaskRefBlockView`, `TaskSettledMarker` /
 * `ConversationMarkers.TaskMarker`, `plan/PlanChecklist`): a presented artifact (opens the
 * generated attachment it maps to, with Preview / Download on hover), a background task started
 * or settled, and the agent's plan as a checklist on a rail. magenticx's gradient tile and card
 * fill are flat token surfaces here (no decorative gradients).
 */
import { motion } from 'framer-motion';
import {
  Bot,
  Check,
  CircleAlert,
  CornerDownRight,
  Download,
  Eye,
  FileText,
  Loader2,
  Sparkles,
} from 'lucide-react';
import { cn } from '@/shared/lib/utils';
import { listItem } from '@/shared/lib/motion';
import { toTitleCase } from '../../lib/hitl';
import type { ArtifactBlock, PlanItem, TaskRefBlock, TaskSettledBlock } from '../../lib/timeline';
import type { AttachmentOut } from '../../lib/types';
import { useChatUi } from '../chatContext';
import { downloadAttachment } from './MessageAttachments';

const ROUND_ACTION =
  'grid size-7 place-items-center rounded-full border border-border/50 bg-background/90 text-text shadow-sm transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

export function ArtifactCard({
  block,
  attachment,
  messageId,
}: {
  block: ArtifactBlock;
  attachment?: AttachmentOut;
  messageId: string;
}) {
  const { openPreview, conversationId } = useChatUi();
  const ready = Boolean(attachment);
  const primary = block.title ?? block.filename;
  const secondary = block.summary || block.path;
  const preview = () => attachment && openPreview({ kind: 'sent', attachment, messageId });
  const download = () =>
    attachment && conversationId && void downloadAttachment(conversationId, messageId, attachment);
  return (
    <motion.div variants={listItem} initial="initial" animate="animate" className="w-full max-w-sm">
      <div
        role={ready ? 'button' : undefined}
        tabIndex={ready ? 0 : undefined}
        aria-label={ready ? `Open ${primary}` : undefined}
        onClick={ready ? preview : undefined}
        onKeyDown={
          ready
            ? (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  preview();
                }
              }
            : undefined
        }
        className={cn(
          'group/artifact relative overflow-hidden rounded-2xl border border-border/60 bg-surface-sunken/40 p-3.5 transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          ready && 'cursor-pointer hover:border-primary/40 hover:bg-surface-sunken/70',
        )}
      >
        <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-primary/80">
          <Sparkles className="size-[11px]" aria-hidden />
          Generated document
        </div>
        <div className="flex items-start gap-3">
          <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-primary text-primary-foreground shadow-sm">
            <FileText className="size-[18px]" />
          </span>
          <div className="min-w-0 flex-1 pr-1">
            <div className="truncate text-sm font-semibold text-text">{primary}</div>
            <div className="mt-0.5 line-clamp-2 text-xs leading-snug text-muted">{secondary}</div>
            {!ready && (
              <div className="mt-2 flex items-center gap-1.5 text-2xs text-muted">
                <Loader2 className="size-3 animate-spin" aria-hidden />
                Preparing…
              </div>
            )}
          </div>
        </div>
        {ready && (
          <div className="pointer-events-none absolute right-2.5 top-2.5 flex items-center gap-1 opacity-0 transition-opacity duration-200 group-focus-within/artifact:pointer-events-auto group-focus-within/artifact:opacity-100 group-hover/artifact:pointer-events-auto group-hover/artifact:opacity-100">
            <button
              type="button"
              aria-label={`Preview ${primary}`}
              className={ROUND_ACTION}
              onClick={(e) => {
                e.stopPropagation();
                preview();
              }}
            >
              <Eye className="size-3.5" />
            </button>
            {conversationId && (
              <button
                type="button"
                aria-label={`Download ${primary}`}
                className={ROUND_ACTION}
                onClick={(e) => {
                  e.stopPropagation();
                  download();
                }}
              >
                <Download className="size-3.5" />
              </button>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}

/** "↳ Started task in the background" over the task's card row. */
export function TaskRefRow({ block }: { block: TaskRefBlock }) {
  const title = toTitleCase(block.name) ?? block.name;
  return (
    <div className="space-y-1.5">
      <p className="flex items-center gap-1.5 px-1 text-xs text-muted">
        <CornerDownRight className="size-3.5 shrink-0" aria-hidden />
        <span className="min-w-0 truncate">
          {block.action === 'update' ? 'Updated task in the background' : 'Started task in the background'}
        </span>
      </p>
      <div className="flex min-w-0 items-center gap-2.5 rounded-[22px] border border-border/70 bg-surface px-3.5 py-2.5 shadow-card">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-primary/10 text-primary">
          <Bot className="size-4" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13.5px] font-semibold text-text">{title}</span>
          {block.description && (
            <span className="block truncate text-xs leading-[1.15rem] text-muted">{block.description}</span>
          )}
        </span>
      </div>
    </div>
  );
}

/** A background task's result arrived: its outcome on a rule. */
export function TaskSettledRow({ block }: { block: TaskSettledBlock }) {
  const ok = block.status === 'success' || block.status === 'completed';
  const name = toTitleCase(block.name) ?? block.name;
  const text = ok ? `${name} finished` : `${name} ${block.status}`;
  return (
    <div role="separator" aria-label={text} className="flex w-full items-center gap-3 py-0.5 text-xs">
      <span aria-hidden className="h-px flex-1 bg-border" />
      <span
        className={cn('flex shrink-0 items-center gap-1.5 font-medium', ok ? 'text-success' : 'text-danger')}
      >
        {ok ? <Check className="size-3.5" /> : <CircleAlert className="size-3.5" />}
        {text}
      </span>
      <span aria-hidden className="h-px flex-1 bg-border" />
    </div>
  );
}

type StepState = 'done' | 'active' | 'pending';
const stepState = (status: string): StepState =>
  status === 'completed' ? 'done' : status === 'in_progress' ? 'active' : 'pending';

function Marker({ state }: { state: StepState }) {
  if (state === 'done')
    return (
      <span className="grid size-5 place-items-center rounded-full bg-primary text-primary-foreground">
        <Check className="size-3" strokeWidth={3.25} />
      </span>
    );
  if (state === 'active')
    return (
      <span className="grid size-5 place-items-center rounded-full border-2 border-primary bg-surface">
        <span className="size-2 rounded-full bg-primary" />
      </span>
    );
  return <span className="block size-5 rounded-full border-[1.5px] border-muted/30 bg-surface" />;
}

/** The agent's plan: a marker per step on a rail, filled in behind the steps that are done. */
export function PlanChecklist({ items }: { items: PlanItem[] }) {
  const done = items.filter((i) => i.status === 'completed').length;
  return (
    <div className="rounded-2xl border border-border/70 bg-surface p-3 shadow-card">
      <div className="mb-1 flex items-center gap-2 px-1 text-2xs font-semibold uppercase tracking-[0.16em] text-muted">
        Plan
        <span className="num ml-auto font-normal normal-case tracking-normal">
          {done}/{items.length}
        </span>
      </div>
      <ol aria-label="Plan" className="relative">
        {items.map((item, i) => {
          const state = stepState(item.status);
          const last = i === items.length - 1;
          return (
            <motion.li
              key={`${i}-${item.content}`}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1], delay: Math.min(i, 12) * 0.035 }}
              aria-current={state === 'active' ? 'step' : undefined}
              className="relative grid grid-cols-[1.5rem_minmax(0,1fr)] gap-x-2"
            >
              {!last && (
                <span
                  aria-hidden
                  className={cn(
                    'absolute bottom-[-1.25rem] left-[calc(0.75rem-0.5px)] top-[1.25rem] w-px',
                    state === 'done' ? 'bg-primary/60' : 'bg-primary/20',
                  )}
                />
              )}
              <span className="relative z-[1] mt-2.5 justify-self-center">
                <Marker state={state} />
              </span>
              <div
                className={cn(
                  'flex items-start gap-3 rounded-xl px-3 py-2.5',
                  state === 'active' && 'bg-primary/5',
                )}
              >
                <p
                  className={cn(
                    'min-w-0 flex-1 text-sm leading-5',
                    state === 'done'
                      ? 'text-muted'
                      : state === 'active'
                        ? 'font-medium text-text'
                        : 'text-muted/80',
                  )}
                >
                  {item.content}
                </p>
                {state === 'active' && (
                  <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-primary/10 px-2 py-0.5 text-2xs font-medium text-primary">
                    <span className="relative flex size-1.5">
                      <span className="absolute inline-flex size-full rounded-full bg-current opacity-70 motion-safe:animate-ping" />
                      <span className="relative inline-flex size-1.5 rounded-full bg-current" />
                    </span>
                    now
                  </span>
                )}
              </div>
            </motion.li>
          );
        })}
      </ol>
    </div>
  );
}
