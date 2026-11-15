import { describe, expect, it } from 'vitest';
import type { BranchMessage } from './agentMap';
import {
  buildConversationPlans,
  collectPlanAnswers,
  formatStepDuration,
  planProgressLabel,
  planStepLabel,
} from './conversationPlans';
import { advancePlanTimings, planStepDurationMs, planStepKeys } from './planTiming';
import { createTimeline, foldTimeline, reduceTimelineEvents } from './timeline';
import type { RawEvent } from './types';

const plan = (updatedAt: number, ...steps: [string, string][]): RawEvent => ({
  type: 'CUSTOM',
  name: 'PLAN_SNAPSHOT',
  value: { items: steps.map(([content, status]) => ({ content, status })), updated_at: updatedAt },
});

const snapshots = [
  plan(1_000, ['Collect findings', 'in_progress'], ['Check evidence', 'pending'], ['Summarise', 'pending']),
  plan(
    13_000,
    ['Collect findings', 'completed'],
    ['Check evidence', 'in_progress'],
    ['Summarise', 'pending'],
  ),
  plan(
    20_000,
    ['Collect findings', 'completed'],
    ['Check evidence', 'completed'],
    ['Summarise', 'in_progress'],
  ),
].map((e, i) => ({ ...e, seq: i + 1 }));

describe('plan timings', () => {
  it('stamps real transitions only', () => {
    const t = reduceTimelineEvents(createTimeline(), snapshots);
    expect(t.plan?.map((s) => s.status)).toEqual(['completed', 'completed', 'in_progress']);
    expect(t.planTimings.map(planStepDurationMs)).toEqual([12_000, 7_000, null]);
  });

  it('leaves a step done before the first snapshot without a time', () => {
    const items = [{ content: 'Done already', status: 'completed' }];
    expect(advancePlanTimings(null, [], items, 5)).toEqual([{ startedAt: null, endedAt: null }]);
  });

  it('keeps a reworded step’s timing and numbers duplicate texts', () => {
    const before = [{ content: 'Read Art 10', status: 'in_progress' }];
    const timings = advancePlanTimings(null, [], before, 100);
    const after = [{ content: 'Read Art. 10(2)', status: 'completed' }];
    expect(planStepDurationMs(advancePlanTimings(before, timings, after, 400)[0])).toBe(300);
    expect(
      planStepKeys([
        { content: 'A', status: '' },
        { content: ' a ', status: '' },
      ]),
    ).toEqual(['a', 'a#1']);
  });
});

describe('conversation plans', () => {
  const messages: BranchMessage[] = [
    { id: 'u1', sender: 'user', content: 'Audit SYS-001' },
    { id: 'a1', sender: 'ai' },
    { id: 'n1', sender: 'user', kind: 'task_notification', content: 'task done' },
    { id: 'a2', sender: 'ai' },
    { id: 'u3', sender: 'user', content: 'Something else' },
    { id: 'a3', sender: 'ai' },
  ];

  it('marks the live step active and a stopped one as not finished', () => {
    const live = reduceTimelineEvents(createTimeline(), snapshots);
    const plans = buildConversationPlans(
      collectPlanAnswers(messages.slice(0, 2), () => ({ timeline: live, live: true })),
    );
    const current = plans.current!;
    expect(current.steps.map((s) => s.state)).toEqual(['done', 'done', 'active']);
    expect(current.activeIndex).toBe(2);
    expect(planProgressLabel(current)).toBe('2 of 3 done');
    expect(planStepLabel(current.steps[0], 0, 3)).toBe('Step 1 of 3, done in 0:12: Collect findings');

    const stopped = foldTimeline(snapshots, { status: 'cancelled' });
    const after = buildConversationPlans(
      collectPlanAnswers(messages.slice(0, 2), () => ({ timeline: stopped, live: false })),
    );
    expect(after.current?.steps[2].state).toBe('stopped');
    expect(after.current?.activeIndex).toBe(-1);
  });

  it('merges the same plan written again by a wake-up answer; a different plan is its own entry', () => {
    const first = reduceTimelineEvents(createTimeline(), snapshots.slice(0, 2));
    const wake = reduceTimelineEvents(createTimeline(), [
      {
        ...plan(
          30_000,
          ['Collect findings', 'completed'],
          ['Check evidence', 'completed'],
          ['Summarise', 'completed'],
        ),
        seq: 1,
      },
    ]);
    const other = reduceTimelineEvents(createTimeline(), [
      { ...plan(40_000, ['Look up Art. 15', 'pending']), seq: 1 },
    ]);
    const byId = { a1: first, a2: wake, a3: other } as const;
    const plans = buildConversationPlans(
      collectPlanAnswers(messages, (m) => ({ timeline: byId[m.id as keyof typeof byId], live: false })),
    );
    expect(plans.answers).toHaveLength(2);
    // The notice is not a question: the wake-up answer keeps question 1, and its step times.
    expect(plans.answers[0]).toMatchObject({ id: 'a1', number: 1, question: 'Audit SYS-001', completed: 3 });
    expect(plans.answers[0].steps[0].durationMs).toBe(12_000);
    expect(planProgressLabel(plans.answers[0])).toBe('Done · 3 steps');
    expect(plans.current?.id).toBe('a3');
    expect(plans.current?.number).toBe(2);
  });

  it('is empty without a plan', () => {
    expect(
      buildConversationPlans(collectPlanAnswers(messages, () => ({ timeline: null, live: false }))),
    ).toEqual({
      answers: [],
      current: null,
    });
  });

  it('formats step durations', () => {
    expect(formatStepDuration(12_000)).toBe('0:12');
    expect(formatStepDuration(185_000)).toBe('3:05');
    expect(formatStepDuration(3_725_000)).toBe('1:02:05');
    expect(formatStepDuration(null)).toBeNull();
  });
});
