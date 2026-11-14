/**
 * The chain of thought (magenticx `message_parts/CoTBlock.tsx`): a collapsible block of thoughts
 * and tool steps. Open while the agent works, folded to a one-line summary ("Thought for 4 s ·
 * 2 tools") once it is done; an `ask_user` item shows the questions and the answers.
 */
import { Brain, ChevronRight, MessageCircleQuestion } from 'lucide-react';
import { useEffect, useState } from 'react';
import { cn } from '@/shared/lib/utils';
import { AgentThinking } from '@/shared/ui';
import type { Approval, ThinkingBlock as Block } from '../../lib/timeline';
import { ToolCallView } from './ToolCallView';

function seconds(start?: number, end?: number) {
  if (!start || !end || end <= start) return null;
  const s = Math.round((end - start) / 1000);
  return s < 1 ? '<1 s' : `${s} s`;
}

function AskUserRecord({ item }: { item: Approval }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-2.5 text-xs">
      <div className="mb-1.5 flex items-center gap-1.5 font-medium">
        <MessageCircleQuestion className="size-3.5 text-primary" />
        {item.status === 'pending'
          ? 'Waiting for your answer'
          : item.status === 'rejected'
            ? 'Questions skipped'
            : 'You answered'}
      </div>
      <ul className="space-y-1">
        {item.questions?.map((q) => {
          const a = item.answers?.find((x) => x.id === q.id);
          const text = a ? [...a.selected, a.text].filter(Boolean).join(' · ') : '';
          return (
            <li key={q.id}>
              <span className="text-muted">{q.question}</span>
              {text && <span className="ml-1.5 font-medium">{text}</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function ThinkingBlock({ block, live }: { block: Block; live: boolean }) {
  const working = live && block.endedAt === undefined;
  const [open, setOpen] = useState(working);
  useEffect(() => {
    setOpen(working);
  }, [working]);
  const waiting = block.items.some(
    (i) =>
      (i.kind === 'hitl' && i.status === 'pending') ||
      (i.kind === 'tool' && i.approval?.status === 'pending'),
  );
  const tools = block.items.filter((i) => i.kind === 'tool').length;
  const took = seconds(block.startedAt, block.endedAt);
  const lastThought = [...block.items].reverse().find((i) => i.kind === 'thought');
  const summary = [
    took ? `Thought for ${took}` : 'Thought',
    tools ? `${tools} tool${tools > 1 ? 's' : ''}` : null,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <div className="group/think">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-md py-0.5 text-xs text-muted transition-colors hover:text-text"
      >
        {working ? (
          waiting ? (
            <span className="font-medium text-warning">Waiting for you</span>
          ) : (
            <AgentThinking size="sm" label={lastThought ? 'Thinking' : 'Working'} />
          )
        ) : (
          <>
            <Brain className="size-3.5" />
            <span>{summary}</span>
          </>
        )}
        <ChevronRight className={cn('size-3.5 transition-transform', open && 'rotate-90')} />
      </button>
      {open && (
        <div className="ml-[7px] mt-1.5 space-y-2 border-l border-border pl-3.5">
          {block.items.map((item) => {
            if (item.kind === 'thought')
              return (
                <p key={item.id} className="whitespace-pre-wrap text-xs leading-relaxed text-muted">
                  {item.text}
                </p>
              );
            if (item.kind === 'tool') return <ToolCallView key={item.id} tool={item} />;
            if (item.questions) return <AskUserRecord key={item.id} item={item} />;
            return (
              <div key={item.id} className="text-xs text-muted">
                Approval {item.status === 'pending' ? 'requested' : item.status}
                {item.reason ? `: ${item.reason}` : ''}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
