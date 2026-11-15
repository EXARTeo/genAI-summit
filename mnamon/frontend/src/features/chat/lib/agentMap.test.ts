import { describe, expect, it } from 'vitest';
import {
  agentNodeDuration,
  agentTranscript,
  buildAgentMap,
  collectAgentMapAnswers,
  flattenAgentNodes,
  formatAgentDuration,
  taskAgentNodes,
  type BranchMessage,
  type TaskRecord,
} from './agentMap';
import { answerFlowNodeIds, buildAgentMapFlow, layoutTree } from './agentMapFlow';
import { resolveSubagentParents, subagentTree } from './subagentTree';
import {
  createTimeline,
  foldTimeline,
  reduceTimelineEvents,
  type RunTimeline,
  type SubagentBlock,
} from './timeline';
import type { RawEvent } from './types';

const custom = (name: string, value: unknown): RawEvent => ({ type: 'CUSTOM', name, value });
const wrap = (taskId: string, namespace: string[], event: RawEvent): RawEvent =>
  custom('SUBAGENT_EVENT', { task_id: taskId, namespace, event });

/**
 * What the agents service's normalizer sends when the orchestrator delegates to a researcher,
 * which delegates to an analyst in turn, plus a second, parallel researcher.
 */
function nestedRun(): RawEvent[] {
  return [
    custom('TASK_SUBAGENT', {
      task_id: 'call-a',
      subagent_type: 'regulation-researcher',
      description: 'Art. 10',
    }),
    custom('TASK_SUBAGENT', {
      task_id: 'call-c',
      subagent_type: 'regulation-researcher',
      description: 'Art. 15',
    }),
    wrap('call-a', ['tools:n1'], custom('BEFORE_AGENT_EVENT', { message: 'What does Article 10 require?' })),
    wrap('call-c', ['tools:n3'], { type: 'TEXT_MESSAGE_CONTENT', delta: 'Art. 15 says…' }),
    wrap('call-a', ['tools:n1'], {
      type: 'TOOL_CALL_START',
      toolCallId: 't1',
      toolCallName: 'search_regulation',
    }),
    wrap('call-a', ['tools:n1'], { type: 'TOOL_CALL_RESULT', toolCallId: 't1', content: 'hits' }),
    // The researcher delegates: its `task` call arrives inside its own envelope.
    wrap(
      'call-a',
      ['tools:n1'],
      custom('TASK_SUBAGENT', {
        task_id: 'call-b',
        subagent_type: 'evidence-analyst',
        description: 'Check F-001',
      }),
    ),
    wrap('call-b', ['tools:n1', 'tools:n2'], { type: 'TEXT_MESSAGE_CONTENT', delta: 'F-001 holds.' }),
    wrap(
      'call-a',
      ['tools:n1'],
      custom('SUBAGENT_COMPLETED', {
        task_id: 'call-b',
        status: 'completed',
        namespace: ['tools:n1', 'tools:n2'],
        started_at: 1_000,
        ended_at: 4_000,
      }),
    ),
    custom('SUBAGENT_COMPLETED', { task_id: 'call-a', status: 'completed', namespace: ['tools:n1'] }),
  ].map((event, i) => ({ ...event, seq: i + 1, timestamp: 1_000 + i * 100 }));
}

const subagents = (t: RunTimeline) => t.blocks.filter((b): b is SubagentBlock => b.kind === 'subagent');

describe('nested sub-agents in the timeline fold', () => {
  it('names a nested sub-agent from the task call its parent made, and settles it mid-run', () => {
    const t = reduceTimelineEvents(createTimeline(), nestedRun());
    const [a, c, b] = subagents(t);
    expect(a).toMatchObject({ taskId: 'call-a', status: 'done', prompt: 'What does Article 10 require?' });
    expect(c).toMatchObject({ taskId: 'call-c', status: 'running' });
    expect(b).toMatchObject({
      taskId: 'call-b',
      type: 'evidence-analyst',
      label: 'Evidence Analyst',
      description: 'Check F-001',
      parentTaskId: 'call-a',
      namespace: 'tools:n1 / tools:n2',
      status: 'done',
      startedAt: 1_000,
      endedAt: 4_000,
    });
  });

  it('resolves parents by namespace prefix, falling back to the parent task id', () => {
    const t = reduceTimelineEvents(createTimeline(), nestedRun());
    const blocks = subagents(t);
    expect(resolveSubagentParents(blocks)).toEqual([-1, -1, 0]);
    const noNamespace = blocks.map((b) => ({ ...b, namespace: undefined }));
    expect(resolveSubagentParents(noNamespace)).toEqual([-1, -1, 0]);
    const tree = subagentTree(t);
    expect(tree.roots.map((b) => b.taskId)).toEqual(['call-a', 'call-c']);
    expect(tree.childrenOf(blocks[0]).map((b) => b.taskId)).toEqual(['call-b']);
    expect(tree.isNested(blocks[2])).toBe(true);
  });

  it('never closes a loop through parentTaskId', () => {
    const block = (taskId: string, parentTaskId: string): SubagentBlock => ({
      kind: 'subagent',
      id: taskId,
      taskId,
      parentTaskId,
      status: 'done',
      spawned: true,
      blocks: [],
    });
    expect(resolveSubagentParents([block('x', 'y'), block('y', 'x')])).toEqual([1, -1]);
  });
});

describe('the agent map', () => {
  const messages: BranchMessage[] = [
    { id: 'u1', sender: 'user', content: 'Explain   Art. 10\nand Art. 15' },
    { id: 'a1', sender: 'ai' },
    { id: 'u2', sender: 'user', content: 'Thanks' },
    { id: 'a2', sender: 'ai' },
  ];

  it('builds one answer per question that used sub-agents, nested children under their parent', () => {
    const live = reduceTimelineEvents(createTimeline(), nestedRun());
    const map = buildAgentMap(
      collectAgentMapAnswers(messages, (m) =>
        m.id === 'a1' ? { timeline: live, live: true } : { timeline: foldTimeline([]), live: false },
      ),
    );
    expect(map.answers).toHaveLength(1);
    const [answer] = map.answers;
    expect(answer).toMatchObject({
      id: 'a1',
      number: 1,
      question: 'Explain Art. 10 and Art. 15',
      live: true,
    });
    expect(answer.nodes.map((n) => n.title)).toEqual(['Regulation Researcher', 'Regulation Researcher']);
    expect(answer.nodes[0].children.map((n) => [n.title, n.depth, n.status])).toEqual([
      ['Evidence Analyst', 2, 'done'],
    ]);
    expect(answer.nodes[0].toolCount).toBe(1);
    expect(answer.nodes[0].task).toBe('Art. 10');
    expect(map.subagentCount).toBe(3);
    expect(map.runningCount).toBe(1);
    expect(flattenAgentNodes(answer.nodes).map((n) => n.taskId)).toEqual(['call-a', 'call-b', 'call-c']);
    expect(answer.nodes[0].children[0].durationMs).toBe(3_000);
  });

  it('shows a settled run as stopped, never as still working', () => {
    const settled = foldTimeline(nestedRun(), { status: 'cancelled' });
    const map = buildAgentMap(
      collectAgentMapAnswers(messages.slice(0, 2), () => ({ timeline: settled, live: false })),
    );
    expect(map.runningCount).toBe(0);
    expect(map.answers[0].nodes[1].status).toBe('cancelled');
  });

  it('is empty when no answer delegated', () => {
    const map = buildAgentMap(
      collectAgentMapAnswers(messages, () => ({ timeline: createTimeline(), live: false })),
    );
    expect(map).toEqual({ answers: [], subagentCount: 0, runningCount: 0 });
  });

  it('turns a node into the transcript the detail view renders', () => {
    const t = reduceTimelineEvents(createTimeline(), nestedRun());
    const map = buildAgentMap([{ messageId: 'a1', number: 1, question: 'q', timeline: t, live: false }]);
    const transcript = agentTranscript(map.answers[0].nodes[0]);
    expect(transcript.instruction).toBe('What does Article 10 require?');
    expect(transcript.timeline.blocks.map((b) => b.kind)).toEqual(['thinking', 'subagent']);
    expect(transcript.timeline.terminalStatus).toBe('completed');
  });

  it('formats working time', () => {
    expect(formatAgentDuration(400)).toBe('<1s');
    expect(formatAgentDuration(42_000)).toBe('42s');
    expect(formatAgentDuration(185_000)).toBe('3m 05s');
    expect(formatAgentDuration(3_720_000)).toBe('1h 02m');
    expect(formatAgentDuration(-1)).toBeNull();
    const t = reduceTimelineEvents(createTimeline(), nestedRun());
    const running = buildAgentMap([{ messageId: 'a', number: 1, question: '', timeline: t, live: true }])
      .answers[0].nodes[1];
    expect(agentNodeDuration(running, (running.startedAt ?? 0) + 5_000)).toBe('5s');
  });
});

describe('the agent map flow layout', () => {
  it('centres parents over their children and never overlaps siblings', () => {
    const boxes = layoutTree(
      {
        id: 'r',
        width: 100,
        height: 20,
        children: [
          { id: 'a', width: 40, height: 20, children: [] },
          { id: 'b', width: 40, height: 20, children: [] },
        ],
      },
      { siblingGap: 10, groupGap: 10, levelGap: 30 },
    );
    const [a, b, r] = [boxes.get('a')!, boxes.get('b')!, boxes.get('r')!];
    expect(b.x - (a.x + a.width)).toBeGreaterThanOrEqual(10);
    expect(a.y).toBe(50);
    expect(r.x + r.width / 2).toBeCloseTo((a.x + b.x + b.width) / 2, 0);
  });

  it('draws one edge per parent → child, lit into a running sub-agent', () => {
    const t = reduceTimelineEvents(createTimeline(), nestedRun());
    const map = buildAgentMap([{ messageId: 'a1', number: 1, question: 'q', timeline: t, live: true }]);
    const flow = buildAgentMapFlow(map, { agentName: 'Mnamon Copilot' });
    expect(flow.nodes.map((n) => n.type)).toEqual([
      'agentRoot',
      'agentAnswer',
      'agentSubagent',
      'agentSubagent',
      'agentSubagent',
    ]);
    expect(flow.edges).toHaveLength(4);
    const running = flow.edges.find((e) => e.target === 'a1/call-c');
    expect(running?.data?.tone).toBe('running');
    expect(running?.animated).toBe(true);
    expect(answerFlowNodeIds(map.answers[0])).toHaveLength(4);
  });
});

describe('background tasks on the agent map', () => {
  const task = (id: string, extra: Partial<TaskRecord> = {}): TaskRecord => ({
    task_id: id,
    name: 'regulation-researcher',
    description: `Question ${id}`,
    status: 'success',
    spawned_by_message_id: 'a1',
    started_at: '2026-11-15T00:00:00Z',
    settled_at: '2026-11-15T00:00:09Z',
    result_preview: 'Answer',
    ...extra,
  });

  it('nests tasks by parent under the answer that launched them, with their status and result', () => {
    const tasks = [
      task('t1'),
      task('t2', { name: 'evidence-analyst', parent_task_id: 't1', status: 'running', settled_at: null }),
      task('t3', { status: 'error', error: 'boom', started_at: '2026-11-15T00:00:01Z' }),
      task('other', { spawned_by_message_id: 'a9' }),
    ];
    const nodes = taskAgentNodes('a1', tasks);
    expect(nodes.map((n) => [n.taskId, n.status])).toEqual([
      ['t1', 'done'],
      ['t3', 'failed'],
    ]);
    expect(nodes[0]).toMatchObject({
      title: 'Regulation Researcher',
      durationMs: 9_000,
      task: 'Question t1',
    });
    expect(nodes[0].children.map((n) => [n.title, n.depth, n.status])).toEqual([
      ['Evidence Analyst', 2, 'running'],
    ]);
    expect(agentTranscript(nodes[1]).timeline.blocks[0]).toMatchObject({
      kind: 'content',
      text: '**Failed:** boom',
    });

    const map = buildAgentMap(
      [
        { messageId: 'a1', number: 1, question: 'q', timeline: createTimeline(), live: false },
        { messageId: 'a2', number: 2, question: 'r', timeline: createTimeline(), live: false },
      ],
      tasks,
    );
    expect(map.answers.map((a) => a.id)).toEqual(['a1']);
    expect(map.subagentCount).toBe(3);
    expect(map.runningCount).toBe(1);
  });

  it('falls back to the root run id and ignores a parent loop', () => {
    const nodes = taskAgentNodes('run-1', [
      task('x', { spawned_by_message_id: null, root_run_id: 'run-1' }),
      task('y', { parent_task_id: 'x' }),
    ]);
    expect(flattenAgentNodes(nodes).map((n) => n.taskId)).toEqual(['x', 'y']);
  });
});
