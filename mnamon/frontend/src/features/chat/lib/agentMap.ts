/**
 * The agent map (composer button → panel; port of magenticx `features/chat/lib/agentMap.ts`):
 * every sub-agent the conversation's main agent delegated to, on the branch the user sees, as a
 * tree.
 *
 *   Main agent
 *   ├─ Q1 · "Compare the three systems…"
 *   │  ├─ Regulation researcher
 *   │  │  └─ Evidence analyst      ← nested: its namespace extends the researcher's
 *   │  └─ Regulation researcher
 *   └─ Q3 · "Re-check finding F-001…"   ← answers without sub-agents are left out
 *      └─ Evidence analyst
 *
 * Pure: the answers' timelines come in, the tree comes out. The adapter (`collectAgentMapAnswers`)
 * reads each answer's timeline through the chat's own `runView` (the live run's fold while it
 * streams, the stored event log once settled), so the map and the messages never disagree.
 * Background tasks (magenticx plan 41; Mnamon runs every sub-agent as one) come from the
 * conversation's task list (`taskAgentNodes`) and hang under the answer that launched them.
 */
import { subagentRunStatus, subagentTree } from './subagentTree';
import {
  createTimeline,
  type ContentBlock,
  type RunTimeline,
  type SubagentBlock,
  type SubagentStatus,
  type TerminalStatus,
  type ThinkingBlock,
  type TimelineBlock,
} from './timeline';
import { toTitleCase } from './hitl';

export interface AgentMapNode {
  /** Unique across the conversation: the answer's message id + the task id. */
  id: string;
  taskId: string;
  messageId: string;
  title: string;
  type?: string;
  /** What it was asked, on one line. */
  task: string;
  status: SubagentStatus | null;
  startedAt?: number;
  endedAt?: number;
  /** How long it worked, once settled; null while it runs or when unknown. */
  durationMs: number | null;
  toolCount: number;
  /** 1 for the main agent's own sub-agents, 2 for theirs, and so on. */
  depth: number;
  /** The folded block, for the detail view. */
  block: SubagentBlock;
  children: AgentMapNode[];
}

export interface AgentMapAnswer {
  /** The answer's message id. */
  id: string;
  /** 1-based number of the question on the branch ("Q3"). */
  number: number;
  question: string;
  live: boolean;
  /** Its sub-agents at every depth. */
  subagentCount: number;
  runningCount: number;
  nodes: AgentMapNode[];
}

export interface AgentMap {
  answers: AgentMapAnswer[];
  subagentCount: number;
  runningCount: number;
}

export interface AgentMapAnswerInput {
  messageId: string;
  number: number;
  question: string;
  timeline: RunTimeline | null;
  /** Whether the run still streams into this answer. */
  live: boolean;
}

/** Tree-row ids: the main agent, and an answer (a node's own id is `node.id`). */
export const AGENT_MAP_ROOT_ID = 'root';
export const answerItemId = (answer: Pick<AgentMapAnswer, 'id'>) => `answer:${answer.id}`;

export const EMPTY_AGENT_MAP: AgentMap = { answers: [], subagentCount: 0, runningCount: 0 };

const SETTLED = new Set<SubagentStatus>(['done', 'failed', 'cancelled']);

export const oneLine = (text: string | undefined | null): string => (text ?? '').replace(/\s+/g, ' ').trim();

function countTools(block: SubagentBlock): number {
  let count = 0;
  for (const nested of block.blocks) {
    if (nested.kind !== 'thinking') continue;
    for (const item of nested.items) if (item.kind === 'tool') count += 1;
  }
  return count;
}

export function subagentTitle(block: SubagentBlock, index = 0): string {
  return block.label || toTitleCase(block.type) || `Sub-agent ${index + 1}`;
}

/** One answer's sub-agents as a forest, in the order they started. */
export function buildAnswerNodes(messageId: string, timeline: RunTimeline, live: boolean): AgentMapNode[] {
  const tree = subagentTree(timeline);
  // Spawned only: an unspawned block is a `task` call that never ran (refused, or not yet).
  const toNode = (block: SubagentBlock, depth: number, index: number): AgentMapNode | null => {
    if (!block.spawned) return null;
    const status = subagentRunStatus(block, timeline, live);
    const settled = status !== null && SETTLED.has(status);
    const { startedAt, endedAt } = block;
    let childIndex = 0;
    return {
      id: `${messageId}/${block.taskId}`,
      taskId: block.taskId,
      messageId,
      title: subagentTitle(block, index),
      type: block.type,
      task: oneLine(block.description || block.prompt),
      status,
      startedAt,
      endedAt,
      durationMs:
        settled && typeof startedAt === 'number' && typeof endedAt === 'number' && endedAt >= startedAt
          ? endedAt - startedAt
          : null,
      toolCount: countTools(block),
      depth,
      block,
      children: tree
        .childrenOf(block)
        .map((child) => toNode(child, depth + 1, childIndex++))
        .filter((node): node is AgentMapNode => node !== null),
    };
  };
  return tree.roots
    .map((block, index) => toNode(block, 1, index))
    .filter((node): node is AgentMapNode => node !== null);
}

/** Every node of a forest, depth first, parents before their children. */
export function flattenAgentNodes(nodes: AgentMapNode[]): AgentMapNode[] {
  const out: AgentMapNode[] = [];
  const visit = (list: AgentMapNode[]) => {
    for (const node of list) {
      out.push(node);
      visit(node.children);
    }
  };
  visit(nodes);
  return out;
}

// An answer is rebuilt only when its timeline (or its live flag, number or question) changes: a
// settled answer's timeline keeps its identity, so a long conversation rebuilds just the one
// that streams.
const answerCache = new WeakMap<RunTimeline, { key: string; answer: AgentMapAnswer | null }>();

function buildAnswer(input: AgentMapAnswerInput): AgentMapAnswer | null {
  const { timeline } = input;
  if (!timeline) return null;
  const key = `${input.messageId}|${input.number}|${input.live}|${input.question}`;
  const cached = answerCache.get(timeline);
  if (cached && cached.key === key) return cached.answer;
  const nodes = buildAnswerNodes(input.messageId, timeline, input.live);
  const all = flattenAgentNodes(nodes);
  const answer: AgentMapAnswer | null = all.length
    ? {
        id: input.messageId,
        number: input.number,
        question: oneLine(input.question),
        live: input.live,
        subagentCount: all.length,
        runningCount: all.filter((node) => node.status === 'running').length,
        nodes,
      }
    : null;
  answerCache.set(timeline, { key, answer });
  return answer;
}

// ---------------------------------------------------------------------------
// Background tasks: Mnamon's sub-agents run as async tasks (ASYNC_SUBAGENTS_ENABLED)
// ---------------------------------------------------------------------------

/** What the map reads off a background task (`GET /v1/conversations/{id}/tasks`, `TaskOut`). */
export interface TaskRecord {
  task_id: string;
  parent_task_id?: string | null;
  root_run_id?: string | null;
  spawned_by_message_id?: string | null;
  name: string;
  description?: string | null;
  status: string;
  result_preview?: string | null;
  error?: string | null;
  started_at?: string | null;
  settled_at?: string | null;
}

const TASK_STATUS: Record<string, SubagentStatus> = {
  pending: 'pending',
  running: 'running',
  waiting_children: 'running',
  waiting: 'awaiting_approval',
  success: 'done',
  completed: 'done',
  error: 'failed',
  failed: 'failed',
  cancelled: 'cancelled',
};

const time = (iso?: string | null): number | undefined => {
  const at = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(at) ? at : undefined;
};

/** The answer a task tree hangs under: the message that launched it (= its root run). */
export const taskAnswerId = (task: TaskRecord): string | null =>
  task.spawned_by_message_id || task.root_run_id || null;

/**
 * An answer's background tasks as map nodes, nested by `parent_task_id`. A task's node carries a
 * sub-agent block made from its record: its instruction, and its result (or error) as the reply.
 */
export function taskAgentNodes(messageId: string, tasks: TaskRecord[]): AgentMapNode[] {
  const ids = new Set(tasks.map((task) => task.task_id));
  const children = new Map<string | null, TaskRecord[]>();
  for (const task of tasks) {
    const parent = task.parent_task_id && ids.has(task.parent_task_id) ? task.parent_task_id : null;
    if (parent === null && taskAnswerId(task) !== messageId) continue;
    const list = children.get(parent) ?? [];
    list.push(task);
    children.set(parent, list);
  }
  const byStart = (a: TaskRecord, b: TaskRecord) => (time(a.started_at) ?? 0) - (time(b.started_at) ?? 0);
  const toNode = (task: TaskRecord, depth: number, seen: Set<string>): AgentMapNode => {
    const status = TASK_STATUS[task.status] ?? 'running';
    const startedAt = time(task.started_at);
    const endedAt = time(task.settled_at);
    const reply = task.error ? `**Failed:** ${task.error}` : (task.result_preview ?? '');
    const block: SubagentBlock = {
      kind: 'subagent',
      id: `task-${task.task_id}`,
      taskId: task.task_id,
      type: task.name,
      label: toTitleCase(task.name),
      description: task.description ?? undefined,
      prompt: task.description ?? undefined,
      spawned: true,
      status,
      startedAt,
      endedAt,
      blocks: reply ? [{ kind: 'content', id: `task-${task.task_id}-result`, text: reply }] : [],
    };
    const next = new Set(seen).add(task.task_id);
    return {
      id: `${messageId}/${task.task_id}`,
      taskId: task.task_id,
      messageId,
      title: subagentTitle(block),
      type: task.name,
      task: oneLine(task.description),
      status,
      startedAt,
      endedAt,
      durationMs:
        SETTLED.has(status) && startedAt !== undefined && endedAt !== undefined && endedAt >= startedAt
          ? endedAt - startedAt
          : null,
      toolCount: 0,
      depth,
      block,
      children: [...(children.get(task.task_id) ?? [])]
        .filter((child) => !next.has(child.task_id))
        .sort(byStart)
        .map((child) => toNode(child, depth + 1, next)),
    };
  };
  return [...(children.get(null) ?? [])].sort(byStart).map((task) => toNode(task, 1, new Set()));
}

/** An answer with its background-task nodes added after its own sub-agents. */
function withTaskNodes(
  input: AgentMapAnswerInput,
  base: AgentMapAnswer | null,
  taskNodes: AgentMapNode[],
): AgentMapAnswer | null {
  if (!taskNodes.length) return base;
  const nodes = [...(base?.nodes ?? []), ...taskNodes];
  const all = flattenAgentNodes(nodes);
  return {
    id: input.messageId,
    number: input.number,
    question: oneLine(input.question),
    live: input.live,
    subagentCount: all.length,
    runningCount: all.filter((node) => node.status === 'running').length,
    nodes,
  };
}

/**
 * The conversation's agent map: one entry per answer that used sub-agents. `tasks` adds the
 * background tasks each answer launched, under the answer that launched them.
 */
export function buildAgentMap(inputs: AgentMapAnswerInput[], tasks: TaskRecord[] = []): AgentMap {
  const answers: AgentMapAnswer[] = [];
  let subagentCount = 0;
  let runningCount = 0;
  for (const input of inputs) {
    const answer = withTaskNodes(
      input,
      buildAnswer(input),
      tasks.length ? taskAgentNodes(input.messageId, tasks) : [],
    );
    if (!answer) continue;
    answers.push(answer);
    subagentCount += answer.subagentCount;
    runningCount += answer.runningCount;
  }
  return answers.length ? { answers, subagentCount, runningCount } : EMPTY_AGENT_MAP;
}

/** What the adapters read off a message on the visible branch. */
export interface BranchMessage {
  id: string;
  sender: string;
  content?: string | null;
  kind?: string | null;
}

/** An answer's timeline and whether it still streams (the chat's `runView`, adapted). */
export type AnswerTimeline = (message: BranchMessage) => { timeline: RunTimeline | null; live: boolean };

/**
 * Pair each answer on the branch with the question before it. A background task's notice is not
 * a question the user asked: the wake-up answer after it carries on the question before it.
 */
export function collectAgentMapAnswers(
  messages: BranchMessage[],
  read: AnswerTimeline,
): AgentMapAnswerInput[] {
  const inputs: AgentMapAnswerInput[] = [];
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
    inputs.push({ messageId: message.id, number: Math.max(number, 1), question, timeline, live });
  }
  return inputs;
}

/** "<1s", "42s", "3m 05s", "1h 02m": a sub-agent's working time. */
export function formatAgentDuration(ms: number | null | undefined): string | null {
  if (typeof ms !== 'number' || !Number.isFinite(ms) || ms < 0) return null;
  const seconds = Math.round(ms / 1000);
  if (seconds < 1) return '<1s';
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${String(seconds % 60).padStart(2, '0')}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m`;
}

/** How long a node has worked: its settled time, or the clock while it runs. */
export function agentNodeDuration(node: AgentMapNode, now: number): string | null {
  if (node.durationMs !== null) return formatAgentDuration(node.durationMs);
  if (node.status === 'running' && typeof node.startedAt === 'number') {
    return formatAgentDuration(Math.max(now - node.startedAt, 0));
  }
  return null;
}

// ---------------------------------------------------------------------------
// One sub-agent as a conversation (the detail view)
// ---------------------------------------------------------------------------

export interface AgentTranscript {
  /** What the agent that delegated asked it to do, in full. */
  instruction: string;
  /** Its reply as the blocks the chat renders (thinking and content), its sub-agents after. */
  timeline: RunTimeline;
  live: boolean;
}

const TERMINAL_STATUS: Partial<Record<SubagentStatus, TerminalStatus>> = {
  done: 'completed',
  failed: 'failed',
  cancelled: 'cancelled',
};

/**
 * A node's reply in the shape the chat renders an answer from: its own thinking and content
 * blocks, then the sub-agents it delegated to (each opens a step deeper in the detail view).
 */
export function agentTranscript(node: AgentMapNode): AgentTranscript {
  const status = node.status;
  const blocks: TimelineBlock[] = [
    ...node.block.blocks.map((block) => block as ThinkingBlock | ContentBlock),
    ...node.children.map((child) => child.block),
  ];
  return {
    instruction: (node.block.prompt || node.block.description || '').trim(),
    live: status === 'running',
    timeline: {
      ...createTimeline(),
      blocks,
      terminal: Boolean(status && TERMINAL_STATUS[status]),
      terminalStatus: status ? TERMINAL_STATUS[status] : undefined,
    },
  };
}
