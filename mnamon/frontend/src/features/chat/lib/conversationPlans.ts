/**
 * The plan panel (composer button → panel; port of magenticx `features/chat/lib/conversationPlans.ts`):
 * the checklist the deep agent keeps with `write_todos`, per answer on the branch the user sees.
 *
 *   Q5 · "Compare the three systems…"   ← the latest plan, open on top
 *     ✓ Collect the findings        0:42
 *     ● Check the evidence          now
 *     ○ Draft the summary
 *   Earlier plans
 *   Q2 · "Summarise the audit"  5/5     ← answers without a plan are left out
 *
 * Pure, like the agent map: the answers' plans come in, the panel's model comes out. Each answer's
 * plan is read off the same run timeline the message renders (`plan` + `planTimings`).
 */
import { oneLine, type AnswerTimeline, type BranchMessage } from './agentMap';
import { planStepDurationMs, planStepKeys, type PlanStepTiming } from './planTiming';
import type { PlanItem, RunTimeline } from './timeline';

/** How a step shows: done, worked on now, left in progress by an answer that ended, or not started. */
export type PlanStepState = 'done' | 'active' | 'stopped' | 'pending';

export interface PlanStep {
  /** Stable across rewrites of the plan (its text), for list keys. */
  key: string;
  content: string;
  status: string;
  state: PlanStepState;
  /** How long it took, once done and both ends are known; else null. */
  durationMs: number | null;
}

export interface PlanAnswer {
  /** The answer's message id. */
  id: string;
  /** 1-based number of the question on the branch ("Q3"). */
  number: number;
  question: string;
  live: boolean;
  steps: PlanStep[];
  completed: number;
  total: number;
  /** The step being worked on now (live answers only), or -1. */
  activeIndex: number;
}

export interface ConversationPlans {
  /** Every answer that kept a plan, in conversation order. */
  answers: PlanAnswer[];
  /** The latest of them: the plan the button and the panel lead with. */
  current: PlanAnswer | null;
}

export interface FoldedPlan {
  items: PlanItem[];
  timings: PlanStepTiming[];
}

export interface PlanAnswerInput {
  messageId: string;
  number: number;
  question: string;
  plan: FoldedPlan | null;
  live: boolean;
}

export const EMPTY_PLANS: ConversationPlans = { answers: [], current: null };

/** One answer's plan as the panel shows it; null when it has no steps. */
export function buildPlanAnswer(input: PlanAnswerInput): PlanAnswer | null {
  const items = input.plan?.items;
  if (!items?.length) return null;
  const keys = planStepKeys(items);
  const timings = input.plan?.timings ?? [];
  const steps = items.map((item, index): PlanStep => {
    const state: PlanStepState =
      item.status === 'completed'
        ? 'done'
        : item.status === 'in_progress'
          ? input.live
            ? 'active'
            : 'stopped'
          : 'pending';
    return {
      key: keys[index],
      content: item.content,
      status: item.status,
      state,
      durationMs: state === 'done' ? planStepDurationMs(timings[index]) : null,
    };
  });
  return {
    id: input.messageId,
    number: input.number,
    question: oneLine(input.question),
    live: input.live,
    steps,
    completed: steps.filter((step) => step.state === 'done').length,
    total: steps.length,
    activeIndex: steps.findIndex((step) => step.state === 'active'),
  };
}

/**
 * A plan's identity: its steps' texts, in order. An update of the same plan changes only
 * statuses; a step added, removed, reworded or moved makes it another plan.
 */
export function planIdentity(answer: Pick<PlanAnswer, 'steps'>): string {
  return answer.steps.map((step) => oneLine(step.content).toLowerCase()).join('␞');
}

/** `later` as an update of `earlier`: keeps the question that started it, takes the new statuses. */
function asPlanUpdate(earlier: PlanAnswer, later: PlanAnswer): PlanAnswer {
  return {
    ...later,
    id: earlier.id,
    number: earlier.number,
    question: earlier.question,
    steps: later.steps.map((step, index) =>
      step.state === 'done' && step.durationMs === null
        ? { ...step, durationMs: earlier.steps[index]?.durationMs ?? null }
        : step,
    ),
  };
}

/**
 * The conversation's plans. The same plan written again by a later answer updates its entry in
 * place; a different plan gets an entry of its own. The plan updated last is the current one.
 */
export function buildConversationPlans(inputs: PlanAnswerInput[]): ConversationPlans {
  const answers: PlanAnswer[] = [];
  const indexByIdentity = new Map<string, number>();
  let currentIndex = -1;
  for (const input of inputs) {
    const answer = buildPlanAnswer(input);
    if (!answer) continue;
    const identity = planIdentity(answer);
    const at = indexByIdentity.get(identity);
    if (at === undefined) {
      indexByIdentity.set(identity, answers.length);
      answers.push(answer);
      currentIndex = answers.length - 1;
    } else {
      answers[at] = asPlanUpdate(answers[at], answer);
      currentIndex = at;
    }
  }
  return answers.length ? { answers, current: answers[currentIndex] } : EMPTY_PLANS;
}

/** A timeline's plan (the main agent's; a sub-agent's own plan stays inside its envelope). */
export function timelinePlan(timeline: RunTimeline | null): FoldedPlan | null {
  if (!timeline?.plan?.length) return null;
  return { items: timeline.plan, timings: timeline.planTimings ?? [] };
}

/** Pair each answer on the branch with the question before it, reading its plan off its timeline. */
export function collectPlanAnswers(messages: BranchMessage[], read: AnswerTimeline): PlanAnswerInput[] {
  const inputs: PlanAnswerInput[] = [];
  let number = 0;
  let question = '';
  for (const message of messages) {
    if (message.sender !== 'ai') {
      if (message.kind === 'task_notification') continue;
      number += 1;
      question = message.content ?? '';
      continue;
    }
    const { timeline, live } = read(message);
    inputs.push({
      messageId: message.id,
      number: Math.max(number, 1),
      question,
      plan: timelinePlan(timeline),
      live,
    });
  }
  return inputs;
}

/** "2 of 5 done", or "Done · 5 steps" once every step is. */
export function planProgressLabel(answer: Pick<PlanAnswer, 'completed' | 'total'>): string {
  if (answer.total > 0 && answer.completed >= answer.total) {
    return `Done · ${answer.total} step${answer.total === 1 ? '' : 's'}`;
  }
  return `${answer.completed} of ${answer.total} done`;
}

const STATE_WORDS: Record<PlanStepState, string> = {
  done: 'done',
  active: 'in progress',
  stopped: 'not finished',
  pending: 'not started',
};

/** "0:12", "3:05", "1:02:05": how long a step took. */
export function formatStepDuration(ms: number | null | undefined): string | null {
  if (typeof ms !== 'number' || !Number.isFinite(ms) || ms < 0) return null;
  const total = Math.round(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}` : `${minutes}:${seconds}`;
}

/** "Step 2 of 5, done in 0:12: Collect the findings": a step's accessible name. */
export function planStepLabel(step: PlanStep, index: number, total: number): string {
  const took = step.state === 'done' ? formatStepDuration(step.durationMs) : null;
  return `Step ${index + 1} of ${total}, ${STATE_WORDS[step.state]}${took ? ` in ${took}` : ''}: ${step.content}`;
}
