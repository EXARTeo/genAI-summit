/**
 * The chain of thought (magenticx `message_parts/CoTBlock.tsx`): one muted header line and,
 * opened, the steps on a vertical guide line: thoughts (dot), tool steps (their own icon,
 * title, duration, PARAMETERS / RESULT), answered questions and resolved approvals, closed
 * by a "Done" footer.
 *
 * The header names the block. Live, it shimmers with the latest step ("Checking the finding",
 * "Read selection_rates.csv") or "Waiting for approval…" / "Waiting for your answer…". Done, it
 * keeps the last step's title with the time after it ("Read selection_rates.csv · 7s"),
 * "Thought for 7s" only when no step names it. Open while the agent works, folded once done.
 */
import { motion, useReducedMotion } from 'framer-motion';
import {
  Check,
  CheckCircle2,
  ChevronDown,
  CircleSlash,
  MessageCircleQuestion,
  ShieldX,
  XCircle,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { color } from '@/shared/lib/consts/ui';
import { cn } from '@/shared/lib/utils';
import { finalCoTTitle, liveCoTTitle, withoutThoughtTitle } from '../../lib/cotTitle';
import { approvalHeadline, hitlActionRequests, isAskUserAnswered } from '../../lib/hitl';
import type { AskUserAnswer, AskUserQuestion } from '../../lib/hitl';
import type { Approval, ThinkingBlock as Block } from '../../lib/timeline';
import { formatThinkingDuration } from '../../lib/toolPresentation';
import { ChatMarkdown } from './ChatMarkdown';
import { CoTStep, Collapse } from './CoTStep';
import { ToolCallView } from './ToolCallView';

export type CoTDoneStatus = 'completed' | 'cancelled' | 'failed';

const SENTINELS: Record<CoTDoneStatus, { icon: LucideIcon; label: string; className: string }> = {
  completed: { icon: CheckCircle2, label: 'Done', className: 'text-success' },
  cancelled: { icon: CircleSlash, label: 'Stopped', className: 'text-muted' },
  failed: { icon: XCircle, label: 'Failed', className: 'text-danger' },
};

// Muted text with a brighter band sweeping across it (the `.text-shimmer` motion, in our tokens).
const MUTED_SHIMMER = {
  backgroundImage: `linear-gradient(90deg, ${color('muted-foreground')} 0%, ${color('muted-foreground')} 40%, ${color('foreground')} 50%, ${color('muted-foreground')} 60%, ${color('muted-foreground')} 100%)`,
};

function AskUserAnswerView({ answer }: { answer: AskUserAnswer | undefined }) {
  if (!answer || !isAskUserAnswered(answer))
    return <p className="text-xs italic text-muted">No preference</p>;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {answer.selected.map((option) => (
        <span
          key={option}
          className="inline-flex max-w-full items-center gap-1 rounded-full border border-primary/25 bg-primary/5 px-2.5 py-0.5 text-xs text-text"
        >
          <Check aria-hidden className="size-3 shrink-0 text-primary" strokeWidth={3} />
          <span className="truncate">{option}</span>
        </span>
      ))}
      {answer.text ? (
        <p className="w-full whitespace-pre-wrap border-l-2 border-primary/30 pl-2.5 text-sm leading-relaxed text-text">
          {answer.text}
        </p>
      ) : null}
    </div>
  );
}

function AskUserList({
  questions,
  answers,
  skipped,
}: {
  questions: AskUserQuestion[];
  answers?: AskUserAnswer[];
  skipped: boolean;
}) {
  return (
    <ol className="space-y-3">
      {questions.map((q, index) => (
        <li key={q.id} className="flex gap-2.5">
          <span
            aria-hidden
            className="num mt-px grid size-5 shrink-0 place-items-center rounded-full bg-surface-sunken text-[10px] font-semibold text-muted"
          >
            {index + 1}
          </span>
          <div className="min-w-0 flex-1 space-y-1.5">
            <p className="text-sm font-medium leading-snug text-text">{q.question}</p>
            {skipped ? (
              <p className="text-xs italic text-muted">Skipped — left to the agent</p>
            ) : answers ? (
              <AskUserAnswerView answer={answers.find((a) => a.id === q.id)} />
            ) : (
              <p className="text-xs italic text-muted">Answer sent</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** A resolved `ask_user`: "Answered · 2 questions", opening onto the questions and answers. */
function AskUserStep({ item, isLast, sole }: { item: Approval; isLast: boolean; sole: boolean }) {
  const [open, setOpen] = useState<boolean | null>(null);
  if (item.status === 'pending') return null; // the takeover is asking
  const questions = item.questions ?? [];
  const skipped = item.status === 'rejected';
  const label = skipped ? 'Skipped' : 'Answered';
  const detail = questions.length === 1 ? questions[0].question : `${questions.length} questions`;
  const expanded = open ?? sole;
  return (
    <CoTStep
      icon={MessageCircleQuestion}
      hideConnector={isLast}
      className={skipped ? 'text-muted' : 'text-primary'}
      label={
        <button
          type="button"
          disabled={!questions.length}
          onClick={() => setOpen(!expanded)}
          aria-expanded={expanded}
          className="flex max-w-full items-center gap-2 text-left transition-colors hover:text-text disabled:cursor-default"
        >
          <span className="shrink-0 font-medium">{label}</span>
          <span className="truncate text-muted">· {detail}</span>
        </button>
      }
    >
      <Collapse open={expanded && questions.length > 0}>
        <div className="pt-1">
          <AskUserList questions={questions} answers={item.answers} skipped={skipped} />
        </div>
      </Collapse>
    </CoTStep>
  );
}

/** A resolved approval not bound to a tool step: "Approved · The agent wants to run …". */
function ApprovalStep({ item, isLast }: { item: Approval; isLast: boolean }) {
  if (item.status === 'pending') return null; // the takeover is the approval surface
  const rejected = item.status === 'rejected';
  return (
    <CoTStep
      icon={rejected ? ShieldX : Check}
      hideConnector={isLast}
      className={rejected ? 'text-danger' : 'text-success'}
      label={
        <span className="flex max-w-full items-center gap-2">
          <span className="shrink-0 font-medium">{rejected ? 'Rejected' : 'Approved'}</span>
          <span className="truncate text-muted">
            · {approvalHeadline(hitlActionRequests(item.content))}
            {rejected && item.reason ? ` — ${item.reason}` : ''}
          </span>
        </span>
      }
    />
  );
}

export function ThinkingBlock({
  block,
  live,
  doneStatus,
}: {
  block: Block;
  /** The run is streaming. */
  live: boolean;
  /**
   * How the footer closes the block once it stopped working. Defaults to "Done"; pass the
   * run's terminal status for its last thinking block ("Stopped", "Failed").
   */
  doneStatus?: CoTDoneStatus;
}) {
  const working = live && block.endedAt === undefined;
  const [open, setOpen] = useState(working);
  useEffect(() => {
    setOpen(working);
  }, [working]);

  // The duration fades in only when the block finishes in front of the user.
  const reduceMotion = useReducedMotion();
  const wasLive = useRef(working);
  const finishedLive = wasLive.current && !working;
  useEffect(() => {
    if (working) wasLive.current = true;
  }, [working]);

  const awaitingAnswer = block.items.some((i) => i.kind === 'hitl' && i.status === 'pending' && i.questions);
  const awaitingApproval = block.items.some(
    (i) =>
      (i.kind === 'hitl' && i.status === 'pending') ||
      (i.kind === 'tool' && i.approval?.status === 'pending'),
  );
  const askedOnly = block.items.length > 0 && block.items.every((i) => i.kind === 'hitl' && i.questions);
  const askedCount = askedOnly
    ? block.items.reduce((n, i) => n + (i.kind === 'hitl' ? (i.questions?.length ?? 0) : 0), 0)
    : 0;
  const status: CoTDoneStatus | null = working ? null : (doneStatus ?? 'completed');
  const sentinel = status && !(askedOnly && status === 'completed') ? SENTINELS[status] : null;
  const duration = formatThinkingDuration(block.startedAt, block.endedAt);
  const finalTitle = working ? null : finalCoTTitle(block.items);
  const liveTitle = working ? liveCoTTitle(block.items) : null;
  if (!block.items.length && !working) return null;

  const liveText = awaitingAnswer
    ? 'Waiting for your answer…'
    : awaitingApproval
      ? 'Waiting for approval…'
      : (liveTitle ?? 'Thinking…');

  return (
    <div className="w-full max-w-full">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex max-w-full items-center gap-1 rounded-sm text-left text-sm font-medium text-muted transition-colors hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:text-[0.95rem]"
      >
        <span className="flex min-w-0 items-baseline gap-1.5">
          {working ? (
            <span
              key={liveText}
              title={liveTitle ?? undefined}
              className="text-shimmer min-w-0 truncate"
              style={MUTED_SHIMMER}
            >
              {liveText}
            </span>
          ) : askedOnly ? (
            <span className="truncate">
              {askedCount === 1 ? 'Asked you a question' : `Asked you ${askedCount} questions`}
            </span>
          ) : finalTitle ? (
            <>
              <span className="truncate" title={finalTitle}>
                {finalTitle}
              </span>
              {duration && (
                <motion.span
                  initial={finishedLive && !reduceMotion ? { opacity: 0, x: -4 } : false}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.3, ease: 'easeOut', delay: 0.1 }}
                  className="num shrink-0 font-normal text-muted/70"
                  aria-label={`thought for ${duration}`}
                >
                  · {duration}
                </motion.span>
              )}
            </>
          ) : (
            <span className="truncate">{duration ? `Thought for ${duration}` : 'Thought'}</span>
          )}
        </span>
        <ChevronDown
          aria-hidden
          className={cn('size-4 shrink-0 transition-transform', open ? 'rotate-180' : 'rotate-0')}
        />
      </button>
      <Collapse open={open}>
        <div className="mt-2 space-y-5 pb-0.5">
          {block.items.map((item, index) => {
            const isLastItem = index === block.items.length - 1;
            const isLast = isLastItem && !sentinel;
            if (item.kind === 'thought')
              return (
                <CoTStep key={item.id} hideConnector={isLast} active={working && isLastItem}>
                  <ChatMarkdown
                    text={withoutThoughtTitle(item.text) || item.text || 'Working…'}
                    className="text-sm leading-relaxed text-muted [&_p]:my-0"
                  />
                </CoTStep>
              );
            if (item.kind === 'tool') return <ToolCallView key={item.id} tool={item} isLast={isLast} />;
            if (item.questions)
              return <AskUserStep key={item.id} item={item} isLast={isLast} sole={askedOnly} />;
            return <ApprovalStep key={item.id} item={item} isLast={isLast} />;
          })}
          {sentinel && (
            <CoTStep
              icon={sentinel.icon}
              hideConnector
              className={cn('font-medium', sentinel.className)}
              label={sentinel.label}
            />
          )}
        </div>
      </Collapse>
    </div>
  );
}
