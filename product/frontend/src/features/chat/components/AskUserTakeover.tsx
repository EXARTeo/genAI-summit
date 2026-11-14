/**
 * The agent's questions (magenticx `AskUserTakeover.tsx`): an `ask_user` interrupt takes over the
 * composer. Each question offers its suggested answers as chips (one or several) plus free text;
 * Send answers all of them, Skip lets the agent go on without.
 */
import { MessageCircleQuestion } from 'lucide-react';
import { useEffect, useState } from 'react';
import { cn } from '@/shared/lib/utils';
import { Button } from '@/shared/ui';
import { isAskUserAnswered, type AskUserAnswer } from '../lib/hitl';
import type { Approval } from '../lib/timeline';

export function AskUserTakeover({
  approval,
  onAnswer,
}: {
  approval: Approval;
  onAnswer: (answers: AskUserAnswer[] | null) => Promise<void>;
}) {
  const questions = approval.questions ?? [];
  const blank = () => questions.map((q) => ({ id: q.id, selected: [] as string[], text: '' }));
  const [answers, setAnswers] = useState<AskUserAnswer[]>(blank);
  const [busy, setBusy] = useState<'send' | 'skip' | null>(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => setAnswers(blank()), [approval.id]);

  const toggle = (qi: number, option: string, multiple: boolean) =>
    setAnswers((list) =>
      list.map((a, i) => {
        if (i !== qi) return a;
        const has = a.selected.includes(option);
        const selected = multiple
          ? has
            ? a.selected.filter((s) => s !== option)
            : [...a.selected, option]
          : has
            ? []
            : [option];
        return { ...a, selected };
      }),
    );

  const submit = async (skip: boolean) => {
    setBusy(skip ? 'skip' : 'send');
    await onAnswer(skip ? null : answers);
  };

  return (
    <div
      className="rounded-2xl border border-primary/40 bg-surface shadow-card"
      role="region"
      aria-label="The agent has questions"
    >
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <span className="grid size-6 place-items-center rounded-md bg-primary/10 text-primary">
          <MessageCircleQuestion className="size-3.5" />
        </span>
        <div>
          <div className="text-sm font-medium">The agent needs a few details</div>
          <div className="text-2xs text-muted">Answer what you can; it goes on once you send</div>
        </div>
      </div>
      <div className="max-h-[45vh] space-y-4 overflow-y-auto px-4 py-3">
        {questions.map((q, qi) => (
          <div key={q.id} className="space-y-2">
            <div className="text-sm">{q.question}</div>
            {q.options.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {q.options.map((o) => {
                  const on = answers[qi]?.selected.includes(o);
                  return (
                    <button
                      key={o}
                      type="button"
                      aria-pressed={on}
                      onClick={() => toggle(qi, o, q.multiple)}
                      className={cn(
                        'rounded-lg border px-2.5 py-1 text-xs transition-colors',
                        on
                          ? 'border-primary bg-primary/10 text-primary'
                          : 'border-border hover:bg-surface-muted',
                      )}
                    >
                      {o}
                    </button>
                  );
                })}
              </div>
            )}
            <input
              value={answers[qi]?.text ?? ''}
              onChange={(e) =>
                setAnswers((list) => list.map((a, i) => (i === qi ? { ...a, text: e.target.value } : a)))
              }
              placeholder={q.options.length ? 'Or in your own words…' : 'Your answer…'}
              aria-label={q.question}
              className="h-8 w-full rounded-lg border border-border bg-background px-3 text-sm outline-none focus:border-primary/50"
            />
          </div>
        ))}
      </div>
      <div className="flex justify-end gap-2 px-4 pb-3">
        <Button
          size="sm"
          variant="ghost"
          loading={busy === 'skip'}
          disabled={Boolean(busy)}
          onClick={() => void submit(true)}
        >
          Skip
        </Button>
        <Button
          size="sm"
          loading={busy === 'send'}
          disabled={Boolean(busy) || !answers.some(isAskUserAnswered)}
          onClick={() => void submit(false)}
        >
          Send answers
        </Button>
      </div>
    </div>
  );
}
