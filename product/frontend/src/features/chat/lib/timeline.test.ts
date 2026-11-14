import { describe, expect, it } from 'vitest';
import { askUserQuestions, hitlActionRequests } from './hitl';
import { mergeRunUpdate } from './runState';
import {
  createTimeline,
  finalizeTimeline,
  foldTimeline,
  pendingInterrupts,
  reduceTimelineEvents,
  timelineText,
  type SubagentBlock,
  type ThinkingBlock,
  type ToolStep,
} from './timeline';
import type { InferenceRunOut, RawEvent } from './types';

const custom = (name: string, value: unknown): RawEvent => ({ type: 'CUSTOM', name, value });
const seq = (events: RawEvent[]) => events.map((e, i) => ({ ...e, seq: i + 1 }));

const interrupt = custom('HITL_INTERRUPT', {
  thread_id: 't',
  interrupt: { id: 'int-1', value: { action_requests: [{ action: 'write_note', args: { path: 'a.md' } }] } },
});

describe('timeline fold', () => {
  it('folds thinking, a tool call and streamed text in log order', () => {
    const t = reduceTimelineEvents(
      createTimeline(),
      seq([
        { type: 'THINKING_START' },
        { type: 'THINKING_TEXT_MESSAGE_CONTENT', delta: 'Let me ' },
        { type: 'THINKING_TEXT_MESSAGE_CONTENT', delta: 'check.' },
        { type: 'TOOL_CALL_START', toolCallId: 'c1', toolCallName: 'search' },
        { type: 'TOOL_CALL_ARGS', toolCallId: 'c1', delta: '{"q":' },
        { type: 'TOOL_CALL_ARGS', toolCallId: 'c1', delta: '"x"}' },
        { type: 'TOOL_CALL_END', toolCallId: 'c1' },
        { type: 'TOOL_CALL_RESULT', toolCallId: 'c1', content: 'found' },
        { type: 'THINKING_END' },
        { type: 'TEXT_MESSAGE_START' },
        { type: 'TEXT_MESSAGE_CONTENT', delta: 'Hello ' },
        { type: 'TEXT_MESSAGE_CONTENT', delta: 'world' },
      ]),
    );
    expect(t.blocks.map((b) => b.kind)).toEqual(['thinking', 'content']);
    const thinking = t.blocks[0] as ThinkingBlock;
    expect(thinking.items[0]).toMatchObject({ kind: 'thought', text: 'Let me check.' });
    expect(thinking.items[1]).toMatchObject({
      kind: 'tool',
      argsText: '{"q":"x"}',
      result: 'found',
      state: 'output-available',
    });
    expect(timelineText(t)).toBe('Hello world');
  });

  it('skips events it has already seen (seq dedupe across snapshot + live frames)', () => {
    const events = seq([
      { type: 'TEXT_MESSAGE_CONTENT', delta: 'a' },
      { type: 'TEXT_MESSAGE_CONTENT', delta: 'b' },
    ]);
    const once = reduceTimelineEvents(createTimeline(), events);
    const twice = reduceTimelineEvents(once, events);
    expect(timelineText(twice)).toBe('ab');
  });

  it('binds an approval to the gated tool, and an approved re-run merges back into the step', () => {
    const before = seq([
      { type: 'THINKING_START' },
      { type: 'TOOL_CALL_START', toolCallId: 'c1', toolCallName: 'write_note' },
      { type: 'TOOL_CALL_END', toolCallId: 'c1' },
      interrupt,
    ]);
    const paused = reduceTimelineEvents(createTimeline(), before);
    const tool = (paused.blocks[0] as ThinkingBlock).items[0] as ToolStep;
    expect(tool.approval?.status).toBe('pending');
    expect(pendingInterrupts(paused).map((i) => i.id)).toEqual(['int-1']);

    const resumed = reduceTimelineEvents(paused, [
      { ...custom('BRIDGE_HITL_RESOLVED', { interrupt_id: 'int-1', decision: 'approve' }), seq: 5 },
      { type: 'TOOL_CALL_START', toolCallId: 'c2', toolCallName: 'write_note', seq: 6 },
      { type: 'TOOL_CALL_RESULT', toolCallId: 'c2', content: 'ok', seq: 7 },
    ]);
    const items = (resumed.blocks[0] as ThinkingBlock).items;
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ approval: { status: 'approved' }, result: 'ok' });
    expect(pendingInterrupts(resumed)).toEqual([]);
  });

  it('a rejected approval marks the step as not run', () => {
    const t = reduceTimelineEvents(
      createTimeline(),
      seq([
        { type: 'TOOL_CALL_START', toolCallId: 'c1', toolCallName: 'write_note' },
        interrupt,
        custom('BRIDGE_HITL_RESOLVED', { interrupt_id: 'int-1', decision: 'reject', reason: 'not now' }),
      ]),
    );
    const tool = (t.blocks[0] as ThinkingBlock).items[0] as ToolStep;
    expect(tool.approval).toMatchObject({ status: 'rejected', reason: 'not now' });
    expect(tool.state).toBe('output-error');
  });

  it('folds a sub-agent and its own events, and settles it on completion', () => {
    const sub = (inner: RawEvent) =>
      custom('SUBAGENT_EVENT', { task_id: 'task-1', namespace: ['ns:1'], event: inner });
    const t = reduceTimelineEvents(
      createTimeline(),
      seq([
        custom('TASK_SUBAGENT', {
          task_id: 'task-1',
          subagent_type: 'evidence-checker',
          description: 'Check',
        }),
        sub({ type: 'TOOL_CALL_START', toolCallId: 's1', toolCallName: 'read' }),
        sub({ type: 'TOOL_CALL_RESULT', toolCallId: 's1', content: 'rows' }),
        sub({ type: 'TEXT_MESSAGE_CONTENT', delta: 'done' }),
        custom('SUBAGENT_COMPLETED', { task_id: 'task-1' }),
      ]),
    );
    const block = t.blocks[0] as SubagentBlock;
    expect(block).toMatchObject({
      kind: 'subagent',
      label: 'Evidence Checker',
      spawned: true,
      status: 'done',
    });
    expect(block.blocks.map((b) => b.kind)).toEqual(['thinking', 'content']);
  });

  it('artifacts, sources, plan and usage', () => {
    const t = reduceTimelineEvents(
      createTimeline(),
      seq([
        { type: 'TOOL_CALL_START', toolCallId: 'c1', toolCallName: 'search' },
        custom('SOURCES', {
          tool_call_id: 'c1',
          sources: [
            { id: 's1', url: 'https://x.eu/a', title: 'A' },
            { id: 'bad', url: 'ftp://no' },
          ],
        }),
        custom('PLAN_SNAPSHOT', {
          items: [
            { content: 'Read', status: 'completed' },
            { content: 'Write', status: 'pending' },
          ],
        }),
        custom('PRESENT_ARTIFACT', {
          artifact_id: 'a1',
          path: 'out/r.md',
          filename: 'r.md',
          title: 'Report',
        }),
        custom('TOKEN_USAGE', { input_tokens: 10, output_tokens: 5, model: 'm' }),
      ]),
    );
    expect(((t.blocks[0] as ThinkingBlock).items[0] as ToolStep).sources?.map((s) => s.id)).toEqual(['s1']);
    expect(t.plan).toHaveLength(2);
    expect(t.blocks[1]).toMatchObject({ kind: 'artifact', filename: 'r.md', title: 'Report' });
    expect(t.usage).toMatchObject({ inputTokens: 10, outputTokens: 5, modelCalls: 1, model: 'm' });
  });

  it('finalize closes running steps; a stored message without events shows its content', () => {
    const t = reduceTimelineEvents(
      createTimeline(),
      seq([{ type: 'TOOL_CALL_START', toolCallId: 'c1', toolCallName: 'x' }]),
    );
    const done = finalizeTimeline(t, 'cancelled');
    expect(done.terminal).toBe(true);
    expect(((done.blocks[0] as ThinkingBlock).items[0] as ToolStep).state).toBe('output-error');
    expect(timelineText(foldTimeline([], { status: 'completed', content: 'old answer' }))).toBe('old answer');
  });
});

describe('hitl parsing', () => {
  it('reads action requests and ask_user questions', () => {
    expect(
      hitlActionRequests({ id: 'x', value: { action_requests: [{ name: 'a', args: { b: 1 } }] } }),
    ).toEqual([{ toolName: 'a', args: { b: 1 }, description: undefined }]);
    const qs = askUserQuestions({
      value: {
        type: 'ask_user',
        questions: [{ question: ' Which? ', options: ['A', 'A', 'B'] }, { question: '' }],
      },
    });
    expect(qs).toEqual([{ id: 'q1', question: 'Which?', options: ['A', 'B'], multiple: false }]);
  });
});

describe('run state', () => {
  const run: InferenceRunOut = {
    id: 'r1',
    conversationId: 'c1',
    assistantMessageId: 'r1',
    status: 'running',
    messagePath: [],
    rawEvents: seq([{ type: 'TEXT_MESSAGE_CONTENT', delta: 'Hi' }]),
    startedAt: '2026-11-14T10:00:00Z',
    updatedAt: '2026-11-14T10:00:00Z',
  };

  it('a snapshot folds the whole log; events frames append; a terminal status finalizes', () => {
    const snap = mergeRunUpdate(null, { type: 'snapshot', run });
    expect(timelineText(snap.timeline)).toBe('Hi');
    const more = mergeRunUpdate(snap, {
      type: 'events',
      run: { id: 'r1', status: 'running', updatedAt: 'x' },
      events: [{ type: 'TEXT_MESSAGE_CONTENT', delta: ' there', seq: 2 }],
    });
    expect(timelineText(more.timeline)).toBe('Hi there');
    const ended = mergeRunUpdate(more, { type: 'update', run: { ...run, status: 'completed' } });
    expect(ended.status).toBe('completed');
    expect(ended.timeline.terminal).toBe(true);
    expect(timelineText(ended.timeline)).toBe('Hi there');
  });
});
