/**
 * The agent's questions (magenticx `AskUserTakeover.tsx`): an `ask_user` interrupt takes over the
 * composer, in the composer's own card. One question at a time: "A few quick questions",
 * "{agent} · question 1 of 2" and step dots; numbered option tiles (keys 1–6 pick, a single
 * choice moves on by itself, arrows walk them), "Write your own answer…" always there, "Skip —
 * let the agent decide" and Next →; the last step shows every answer and sends them together.
 * magenticx's orb is our LogoMark (no glows or gradients here).
 */
import { AnimatePresence, motion, useReducedMotion, type Variants } from 'framer-motion';
import { ArrowLeft, ArrowRight, Check, Loader2, PencilLine, SendHorizontal } from 'lucide-react';
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { cn } from '@/shared/lib/utils';
import { Button, LogoMark } from '@/shared/ui';
import { isAskUserAnswered, type AskUserAnswer, type AskUserQuestion } from '../lib/hitl';
import type { Approval } from '../lib/timeline';

/** How long a single-choice pick stays on screen before the next question slides in. */
const AUTO_ADVANCE_MS = 300;
/** Options this short sit two to a row on wide screens. */
const SHORT_OPTION_CHARS = 28;

const FALLBACK_QUESTION: AskUserQuestion = {
  id: 'q1',
  question: 'The agent needs a little more from you to continue.',
  options: [],
  multiple: false,
};

const blank = (questions: AskUserQuestion[]): AskUserAnswer[] =>
  questions.map((q) => ({ id: q.id, selected: [], text: '' }));

/** One answer as a line: the picks, then the user's own words. */
const answerText = (a: AskUserAnswer | undefined) => {
  if (!a) return '';
  const text = a.text.trim();
  return [a.selected.join(', '), text ? `“${text}”` : ''].filter(Boolean).join(' · ');
};

const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));

function StepDots({
  questions,
  answers,
  step,
  disabled,
  onJump,
}: {
  questions: AskUserQuestion[];
  answers: AskUserAnswer[];
  step: number;
  disabled: boolean;
  onJump: (i: number) => void;
}) {
  return (
    <ol className="flex shrink-0 items-center" aria-label="Questions">
      {questions.map((q, i) => {
        const answered = isAskUserAnswered(answers[i]);
        const current = i === step;
        return (
          <li key={q.id} className="flex items-center">
            {i > 0 && (
              <span
                aria-hidden
                className="relative mx-1 h-0.5 w-3 overflow-hidden rounded-full bg-border sm:w-4"
              >
                <span
                  className={cn(
                    'absolute inset-0 origin-left rounded-full bg-primary transition-transform duration-300 ease-out motion-reduce:transition-none',
                    isAskUserAnswered(answers[i - 1]) ? 'scale-x-100' : 'scale-x-0',
                  )}
                />
              </span>
            )}
            <button
              type="button"
              onClick={() => onJump(i)}
              disabled={disabled}
              aria-current={current ? 'step' : undefined}
              aria-label={`Question ${i + 1}${answered ? ', answered' : ''}`}
              className={cn(
                'num grid size-6 place-items-center rounded-full text-2xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60',
                answered
                  ? 'bg-primary text-primary-foreground'
                  : current
                    ? 'bg-primary/10 text-primary'
                    : 'bg-surface-muted text-muted hover:text-text',
                current && 'ring-2 ring-primary/40 ring-offset-2 ring-offset-surface',
              )}
            >
              {answered ? <Check className="size-3.5" strokeWidth={3} /> : i + 1}
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function OptionTile({
  label,
  index,
  chosen,
  multiple,
  disabled,
  onToggle,
}: {
  label: string;
  index: number;
  chosen: boolean;
  multiple: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      role={multiple ? 'checkbox' : 'radio'}
      aria-checked={chosen}
      aria-keyshortcuts={index < 9 ? String(index + 1) : undefined}
      data-option-index={index}
      disabled={disabled}
      onClick={onToggle}
      className={cn(
        'group flex min-h-[2.75rem] w-full items-center gap-3 rounded-2xl border px-3 py-2.5 text-left text-sm leading-snug transition-[background-color,border-color] duration-150',
        'focus-visible:border-primary/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20 disabled:cursor-default',
        chosen
          ? 'border-primary/55 bg-primary/[0.07]'
          : 'border-border bg-surface-muted/40 hover:border-primary/35 hover:bg-primary/[0.04]',
      )}
    >
      <span
        aria-hidden
        className={cn(
          'num grid size-6 shrink-0 place-items-center border text-2xs font-semibold transition-colors',
          multiple ? 'rounded-md' : 'rounded-full',
          chosen
            ? 'border-primary bg-primary text-primary-foreground'
            : 'border-border bg-surface text-muted group-hover:border-primary/40 group-hover:text-primary',
        )}
      >
        {chosen ? <Check className="size-3.5" strokeWidth={3} /> : index + 1}
      </span>
      <span className="min-w-0 flex-1 break-words">{label}</span>
    </button>
  );
}

export function AskUserTakeover({
  approval,
  agentName,
  onAnswer,
}: {
  approval: Approval;
  /** The agent asking ("Copilot · question 1 of 2"). */
  agentName?: string | null;
  onAnswer: (answers: AskUserAnswer[] | null) => Promise<void>;
}) {
  const reduce = useReducedMotion() ?? false;
  const questions = useMemo(
    () => (approval.questions?.length ? approval.questions : [FALLBACK_QUESTION]),
    [approval.questions],
  );
  const total = questions.length;

  const [answers, setAnswers] = useState<AskUserAnswer[]>(() => blank(questions));
  const [step, setStep] = useState(0);
  const [direction, setDirection] = useState<1 | -1>(1);
  const [busy, setBusy] = useState<'send' | 'skip' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const advance = useRef<ReturnType<typeof setTimeout> | null>(null);
  const panel = useRef<HTMLElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const questionId = useId();

  useEffect(() => {
    setAnswers(blank(questions));
    setStep(0);
    setBusy(null);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [approval.id]);
  useEffect(
    () => () => {
      if (advance.current) clearTimeout(advance.current);
    },
    [],
  );

  const question = questions[step] ?? questions[0];
  const answer = answers[step] ?? { id: question.id, selected: [], text: '' };
  const isLast = step === total - 1;
  const answeredCount = answers.filter(isAskUserAnswered).length;
  const hasOptions = question.options.length > 0;
  const twoColumns =
    question.options.length > 1 && question.options.every((o) => o.length <= SHORT_OPTION_CHARS);

  const stepRoot = useCallback(
    () => body.current?.querySelector<HTMLElement>(`[data-step="${step}"]`) ?? null,
    [step],
  );

  // Each step starts where the hand is: the chosen option, else the first, else the field.
  useEffect(() => {
    const root = stepRoot();
    const target =
      root?.querySelector<HTMLElement>('[aria-checked="true"]') ??
      root?.querySelector<HTMLElement>('[data-option-index]') ??
      root?.querySelector<HTMLElement>('textarea');
    target?.focus({ preventScroll: true });
  }, [stepRoot]);

  // The answer field grows with what is written.
  useLayoutEffect(() => {
    const field = stepRoot()?.querySelector('textarea');
    if (!field) return;
    field.style.height = 'auto';
    field.style.height = `${field.scrollHeight}px`;
  }, [answer.text, stepRoot]);

  const clearAdvance = () => {
    if (advance.current) clearTimeout(advance.current);
    advance.current = null;
  };

  const goTo = (target: number) => {
    clearAdvance();
    const next = Math.max(0, Math.min(target, total - 1));
    if (next === step) return;
    setDirection(next > step ? 1 : -1);
    setStep(next);
  };

  const update = (change: (a: AskUserAnswer) => AskUserAnswer) =>
    setAnswers((list) => list.map((a, i) => (i === step ? change(a) : a)));

  const toggle = (option: string) => {
    if (busy) return;
    setError(null);
    if (question.multiple) {
      update((a) => ({
        ...a,
        selected: a.selected.includes(option)
          ? a.selected.filter((s) => s !== option)
          : [...a.selected, option],
      }));
      return;
    }
    const picking = !answer.selected.includes(option);
    update((a) => ({ ...a, selected: picking ? [option] : [] }));
    // A single-choice pick answers the question: let it land, then move on.
    if (picking && !isLast && !answer.text.trim()) {
      clearAdvance();
      advance.current = setTimeout(() => {
        advance.current = null;
        setDirection(1);
        setStep((s) => Math.min(s + 1, total - 1));
      }, AUTO_ADVANCE_MS);
    }
  };

  const send = async () => {
    if (busy || answeredCount === 0) return;
    clearAdvance();
    setBusy('send');
    setError(null);
    // Picks in the order they were offered, words trimmed.
    const payload = questions.map((q, i) => ({
      id: q.id,
      selected: q.options.filter((o) => answers[i]?.selected.includes(o)),
      text: answers[i]?.text.trim() ?? '',
    }));
    try {
      await onAnswer(payload);
    } catch {
      setBusy(null);
      setError('Your answers were not sent. They are still here, try again.');
    }
  };

  const skip = async () => {
    if (busy) return;
    clearAdvance();
    setBusy('skip');
    setError(null);
    try {
      await onAnswer(null);
    } catch {
      setBusy(null);
      setError('Could not skip. Try again.');
    }
  };

  const next = () => (isLast ? void send() : goTo(step + 1));

  // Keys 1–6 pick an option, unless the user is typing or focus is in another surface.
  const keyHandler = useRef<(e: KeyboardEvent) => void>(() => {});
  keyHandler.current = (e) => {
    if (busy || e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || isTyping(e.target)) return;
    const active = document.activeElement;
    if (active && active !== document.body && !panel.current?.contains(active)) return;
    const key = Number(e.key);
    if (!Number.isInteger(key) || key < 1 || key > question.options.length) return;
    e.preventDefault();
    toggle(question.options[key - 1]);
    stepRoot()
      ?.querySelector<HTMLElement>(`[data-option-index="${key - 1}"]`)
      ?.focus({ preventScroll: true });
  };
  useEffect(() => {
    const listener = (e: KeyboardEvent) => keyHandler.current(e);
    document.addEventListener('keydown', listener);
    return () => document.removeEventListener('keydown', listener);
  }, []);

  // Arrow keys walk the options (and on into the answer field).
  const onOptionsKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const delta =
      e.key === 'ArrowDown' || e.key === 'ArrowRight'
        ? 1
        : e.key === 'ArrowUp' || e.key === 'ArrowLeft'
          ? -1
          : 0;
    if (!delta) return;
    const items = [...e.currentTarget.querySelectorAll<HTMLElement>('[data-option-index]')];
    const i = items.indexOf(document.activeElement as HTMLElement);
    if (i === -1) return;
    e.preventDefault();
    const target = items[i + delta];
    if (target) target.focus();
    else if (delta === 1) stepRoot()?.querySelector('textarea')?.focus();
  };

  const name = agentName?.trim() || 'The agent';
  const title = total > 1 ? 'A few quick questions' : `${name} has a question`;
  const subtitle =
    total > 1
      ? `${name} · question ${step + 1} of ${total}`
      : 'It is paused until you answer, or let it decide.';
  const hint = !hasOptions
    ? 'Answer in your own words'
    : question.multiple
      ? 'Choose all that apply, or write your own'
      : 'Choose one, or write your own';

  const slide: Variants = {
    enter: (dir: 1 | -1) => (reduce ? { opacity: 0 } : { opacity: 0, x: dir * 24 }),
    center: { opacity: 1, x: 0, transition: { duration: reduce ? 0.12 : 0.22, ease: 'easeOut' } },
    exit: (dir: 1 | -1) =>
      reduce
        ? { opacity: 0, transition: { duration: 0.1 } }
        : { opacity: 0, x: dir * -20, transition: { duration: 0.15, ease: 'easeIn' } },
  };

  return (
    <section
      ref={panel}
      aria-labelledby={titleId}
      aria-busy={busy !== null}
      className="overflow-hidden rounded-[1.75rem] border border-border bg-surface shadow-card"
    >
      <header className="flex items-center gap-3 px-4 pt-4 sm:px-5">
        <LogoMark className="size-8 shrink-0" title="" />
        <div className="min-w-0 flex-1">
          <h2 id={titleId} className="truncate text-sm font-semibold">
            {title}
          </h2>
          <p className="truncate text-xs text-muted">{subtitle}</p>
        </div>
        {total > 1 && (
          <StepDots
            questions={questions}
            answers={answers}
            step={step}
            disabled={busy !== null}
            onJump={goTo}
          />
        )}
      </header>

      <div
        ref={body}
        className="relative max-h-[min(30rem,55vh)] overflow-y-auto overflow-x-hidden px-4 pb-1 pt-4 sm:px-5"
      >
        <AnimatePresence mode="popLayout" initial={false} custom={direction}>
          <motion.div
            key={step}
            data-step={step}
            custom={direction}
            variants={slide}
            initial="enter"
            animate="center"
            exit="exit"
            className={cn(busy && 'pointer-events-none opacity-60')}
          >
            <h3 id={questionId} className="text-balance text-base font-semibold leading-snug sm:text-lg">
              {question.question}
            </h3>
            <div className="mt-1 flex items-center justify-between gap-3 text-xs text-muted">
              <span>{hint}</span>
              {hasOptions && (
                <span aria-hidden className="hidden items-center gap-1 sm:inline-flex">
                  Press
                  <kbd className="rounded-md border border-border bg-surface-muted px-1.5 font-sans text-[10px] font-medium text-text">
                    1
                  </kbd>
                  {question.options.length > 1 && (
                    <>
                      –
                      <kbd className="rounded-md border border-border bg-surface-muted px-1.5 font-sans text-[10px] font-medium text-text">
                        {question.options.length}
                      </kbd>
                    </>
                  )}
                </span>
              )}
            </div>

            {hasOptions && (
              <div
                role={question.multiple ? 'group' : 'radiogroup'}
                aria-labelledby={questionId}
                onKeyDown={onOptionsKeyDown}
                className={cn('mt-3 grid gap-2', twoColumns && 'sm:grid-cols-2')}
              >
                {question.options.map((option, i) => (
                  <OptionTile
                    key={option}
                    label={option}
                    index={i}
                    chosen={answer.selected.includes(option)}
                    multiple={question.multiple}
                    disabled={busy !== null}
                    onToggle={() => toggle(option)}
                  />
                ))}
              </div>
            )}

            <label
              className={cn(
                'mt-2 flex cursor-text items-start gap-2.5 rounded-2xl border px-3 transition-[border-color,background-color] duration-150',
                hasOptions ? 'py-2.5' : 'mt-3 py-3',
                'focus-within:border-solid focus-within:border-primary/55 focus-within:bg-surface',
                answer.text.trim()
                  ? 'border-solid border-primary/40 bg-surface'
                  : hasOptions
                    ? 'border-dashed border-border hover:border-primary/35'
                    : 'border-border bg-surface-muted/40',
              )}
            >
              <PencilLine
                aria-hidden
                className={cn('mt-0.5 size-4 shrink-0', answer.text.trim() ? 'text-primary' : 'text-muted')}
              />
              <textarea
                rows={hasOptions ? 1 : 2}
                value={answer.text}
                disabled={busy !== null}
                onChange={(e) => {
                  setError(null);
                  const text = e.target.value;
                  update((a) => ({ ...a, text }));
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    next();
                  }
                }}
                placeholder={hasOptions ? 'Write your own answer…' : 'Write your answer…'}
                aria-label={hasOptions ? `Your own answer to: ${question.question}` : question.question}
                className="max-h-32 min-w-0 flex-1 resize-none bg-transparent text-sm leading-relaxed outline-none placeholder:text-muted disabled:opacity-60"
              />
            </label>
          </motion.div>
        </AnimatePresence>
      </div>

      {isLast && total > 1 && (
        <div className="px-4 pt-3 sm:px-5" role="group" aria-label="Your answers">
          <div className="flex flex-wrap gap-1.5 border-t border-border pt-3">
            {questions.map((q, i) => {
              const text = answerText(answers[i]);
              return (
                <button
                  key={q.id}
                  type="button"
                  onClick={() => goTo(i)}
                  disabled={busy !== null}
                  title={q.question}
                  aria-label={`Question ${i + 1}: ${text || 'no answer'}, edit`}
                  className={cn(
                    'inline-flex max-w-full items-center gap-1.5 rounded-full border py-1 pl-1 pr-2.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60',
                    text
                      ? 'border-primary/25 bg-primary/[0.07] hover:border-primary/45'
                      : 'border-dashed border-border text-muted hover:text-text',
                    i === step && 'border-primary/50',
                  )}
                >
                  <span
                    className={cn(
                      'num grid size-[18px] shrink-0 place-items-center rounded-full text-[10px] font-semibold',
                      text ? 'bg-primary text-primary-foreground' : 'bg-surface-muted text-muted',
                    )}
                  >
                    {i + 1}
                  </span>
                  <span className="truncate sm:max-w-[16rem]">{text || 'No preference'}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="px-4 pt-2 text-xs text-danger sm:px-5">
          {error}
        </p>
      )}

      <footer className="flex items-center gap-2 px-2.5 pb-2.5 pt-3 sm:px-3.5 sm:pb-3">
        <Button
          variant="ghost"
          onClick={() => void skip()}
          disabled={busy !== null}
          leftIcon={busy === 'skip' ? <Loader2 className="animate-spin" /> : undefined}
          className="h-10 rounded-full px-3 font-normal"
        >
          <span>
            Skip<span className="hidden sm:inline"> — let the agent decide</span>
          </span>
        </Button>
        <div className="ml-auto flex items-center gap-1.5">
          {step > 0 && (
            <Button
              variant="ghost"
              onClick={() => goTo(step - 1)}
              disabled={busy !== null}
              aria-label="Previous question"
              leftIcon={<ArrowLeft />}
              className="h-10 rounded-full px-3"
            >
              <span className="hidden sm:inline">Back</span>
            </Button>
          )}
          {isLast ? (
            <Button
              onClick={() => void send()}
              disabled={busy !== null || answeredCount === 0}
              className="h-10 rounded-full px-5"
              rightIcon={busy === 'send' ? <Loader2 className="animate-spin" /> : <SendHorizontal />}
            >
              {busy === 'send' ? 'Sending…' : total > 1 ? 'Send answers' : 'Send answer'}
            </Button>
          ) : (
            <Button
              variant="secondary"
              onClick={next}
              disabled={busy !== null}
              rightIcon={<ArrowRight />}
              className="h-10 rounded-full px-4"
            >
              Next
            </Button>
          )}
        </div>
      </footer>
    </section>
  );
}
