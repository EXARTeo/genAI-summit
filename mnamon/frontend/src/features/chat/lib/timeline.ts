/**
 * The run timeline: the AG-UI event log folded into what the chat renders (port of magenticx
 * `features/inference/timeline.ts`, condensed). The same fold runs on live WebSocket frames
 * (incrementally) and on a stored message's `rawEvents` (hydration), so a live answer and a
 * reloaded one can never drift.
 *
 * Blocks, in log order: `thinking` (thoughts + tool steps + approvals), `content` (answer text),
 * `subagent` (a delegated sub-agent with its own thinking/content), `artifact` (a file the agent
 * presented), `task_ref` / `task_settled` (background tasks). Plus run-level `plan`, `interrupts`,
 * `sources` and `usage`.
 */
import {
  askUserAnswers,
  askUserQuestions,
  hitlActionRequests,
  toTitleCase,
  type AskUserAnswer,
  type AskUserQuestion,
} from './hitl';
import { advancePlanTimings, planSnapshotTime, type PlanStepTiming } from './planTiming';
import type { RawEvent } from './types';

export type ToolState = 'input-streaming' | 'input-available' | 'output-available' | 'output-error';
export type ApprovalStatus = 'pending' | 'approved' | 'rejected';

export interface Approval {
  kind: 'hitl';
  id: string;
  threadId: string;
  content: unknown;
  status: ApprovalStatus;
  reason?: string | null;
  subagentId?: string;
  /** Which action of a batched interrupt this binding is. */
  actionIndex?: number;
  questions?: AskUserQuestion[];
  answers?: AskUserAnswer[];
}

export interface Thought {
  kind: 'thought';
  id: string;
  text: string;
}

export interface Source {
  id: string;
  url: string;
  title?: string;
  snippet?: string;
}

export interface ToolStep {
  kind: 'tool';
  id: string;
  name: string;
  argsText: string;
  /** A re-run folded into this step: the old args stay until the new ones start streaming. */
  argsStale?: boolean;
  result?: string;
  resultTruncated?: boolean;
  state: ToolState;
  approval?: Approval;
  startedAt?: number;
  endedAt?: number;
  sources?: Source[];
}

export type ThinkingItem = Thought | ToolStep | Approval;

export interface ThinkingBlock {
  kind: 'thinking';
  id: string;
  items: ThinkingItem[];
  startedAt?: number;
  endedAt?: number;
}

export interface ContentBlock {
  kind: 'content';
  id: string;
  text: string;
}

export type SubagentStatus = 'pending' | 'running' | 'awaiting_approval' | 'done' | 'failed' | 'cancelled';

export interface SubagentBlock {
  kind: 'subagent';
  id: string;
  taskId: string;
  type?: string;
  label?: string;
  description?: string;
  /** What it was asked, in full (the sub-agent's first input, `BEFORE_AGENT_EVENT`). */
  prompt?: string;
  namespace?: string;
  /** The sub-agent whose `task` call started this one (nested delegation); unset for the main agent's. */
  parentTaskId?: string;
  spawned?: boolean;
  status: SubagentStatus;
  startedAt?: number;
  endedAt?: number;
  blocks: (ThinkingBlock | ContentBlock)[];
}

export interface ArtifactBlock {
  kind: 'artifact';
  id: string;
  artifactId: string;
  path: string;
  filename: string;
  title?: string;
  summary?: string;
  mime?: string;
}

export interface TaskRefBlock {
  kind: 'task_ref';
  id: string;
  taskId: string;
  name: string;
  description?: string;
  action?: 'start' | 'update';
}

export interface TaskSettledBlock {
  kind: 'task_settled';
  id: string;
  taskId: string;
  name: string;
  status: string;
}

export type TimelineBlock =
  | ThinkingBlock
  | ContentBlock
  | SubagentBlock
  | ArtifactBlock
  | TaskRefBlock
  | TaskSettledBlock;

export interface PlanItem {
  content: string;
  status: 'pending' | 'in_progress' | 'completed' | string;
}

export interface RunUsage {
  inputTokens: number;
  outputTokens: number;
  modelCalls: number;
  model?: string;
  contextTokens?: number;
  contextWindow?: number;
  contextPercent?: number;
}

export type TerminalStatus = 'completed' | 'cancelled' | 'failed';

interface ToolPath {
  block: number;
  item: number;
}

interface SubFold {
  openThinking: number | null;
  openContent: number | null;
  toolPaths: Record<string, ToolPath>;
}

interface Fold {
  openThinking: number | null;
  openContent: number | null;
  toolPaths: Record<string, ToolPath>;
  subagentIndexByKey: Record<string, number>;
  namespaceToKey: Record<string, string>;
  subFolds: Record<string, SubFold>;
  /** An approved tool re-executes under a fresh call id: merge it into the stalled step. */
  pendingRetool: (ToolPath & { name: string; subKey?: string }) | null;
  /** `task` calls a sub-agent made (key: the nested call id): who called, and what it asked. */
  nestedTasks: Record<string, { parentKey: string; type?: string; description?: string }>;
  counter: number;
}

export interface RunTimeline {
  blocks: TimelineBlock[];
  plan: PlanItem[] | null;
  /** When each plan step started and finished, index-aligned with `plan` (lib/planTiming). */
  planTimings: PlanStepTiming[];
  interrupts: Approval[];
  sources: Record<string, Source>;
  usage: RunUsage | null;
  terminal: boolean;
  terminalStatus?: TerminalStatus;
  lastSeq: number;
  fold: Fold;
}

export const HITL_INTERRUPT = 'HITL_INTERRUPT';
export const BRIDGE_HITL_RESOLVED = 'BRIDGE_HITL_RESOLVED';
export const SUBAGENT_EVENT = 'SUBAGENT_EVENT';
export const TASK_SUBAGENT = 'TASK_SUBAGENT';
export const SUBAGENT_COMPLETED = 'SUBAGENT_COMPLETED';
export const BEFORE_AGENT_EVENT = 'BEFORE_AGENT_EVENT';
export const PRESENT_ARTIFACT = 'PRESENT_ARTIFACT';
export const PLAN_SNAPSHOT = 'PLAN_SNAPSHOT';
export const TOKEN_USAGE = 'TOKEN_USAGE';
export const SOURCES = 'SOURCES';
export const TASK_LAUNCHED = 'TASK_LAUNCHED';
export const TASK_SETTLED_INLINE = 'TASK_SETTLED_INLINE';

const TEXT_DELTA = new Set(['TEXT_MESSAGE_CHUNK', 'TEXT_MESSAGE_CONTENT']);

export function createTimeline(): RunTimeline {
  return {
    blocks: [],
    plan: null,
    planTimings: [],
    interrupts: [],
    sources: {},
    usage: null,
    terminal: false,
    lastSeq: -1,
    fold: {
      openThinking: null,
      openContent: null,
      toolPaths: {},
      subagentIndexByKey: {},
      namespaceToKey: {},
      subFolds: {},
      pendingRetool: null,
      nestedTasks: {},
      counter: 0,
    },
  };
}

const rec = (v: unknown): Record<string, unknown> =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
const str = (v: unknown): string | undefined => (typeof v === 'string' && v ? v : undefined);
const num = (v: unknown): number | undefined => (typeof v === 'number' && Number.isFinite(v) ? v : undefined);

function nextId(state: RunTimeline, prefix: string): string {
  state.fold.counter += 1;
  return `${prefix}-${state.fold.counter}`;
}

function ts(event: RawEvent): number | undefined {
  return num(event.timestamp);
}

// ---------------------------------------------------------------------------
// Block helpers: a "scope" is either the main run or one sub-agent's blocks.
// ---------------------------------------------------------------------------
interface Scope {
  blocks: (ThinkingBlock | ContentBlock | TimelineBlock)[];
  fold: SubFold | Fold;
  subKey?: string;
}

function closeThinking(scope: Scope, at?: number) {
  const i = scope.fold.openThinking;
  if (i !== null) {
    const block = scope.blocks[i] as ThinkingBlock;
    if (block && block.endedAt === undefined) block.endedAt = at;
  }
  scope.fold.openThinking = null;
}

function ensureThinking(state: RunTimeline, scope: Scope, at?: number): ThinkingBlock {
  const open = scope.fold.openThinking;
  if (open !== null) return scope.blocks[open] as ThinkingBlock;
  scope.fold.openContent = null;
  const block: ThinkingBlock = { kind: 'thinking', id: nextId(state, 'think'), items: [], startedAt: at };
  scope.blocks.push(block);
  scope.fold.openThinking = scope.blocks.length - 1;
  return block;
}

function ensureContent(state: RunTimeline, scope: Scope, at?: number): ContentBlock {
  const open = scope.fold.openContent;
  if (open !== null) return scope.blocks[open] as ContentBlock;
  closeThinking(scope, at);
  const block: ContentBlock = { kind: 'content', id: nextId(state, 'text'), text: '' };
  scope.blocks.push(block);
  scope.fold.openContent = scope.blocks.length - 1;
  return block;
}

/** Push a standalone block (artifact, task ref…) and close the open thinking/content around it. */
function pushStandalone(state: RunTimeline, block: TimelineBlock, at?: number) {
  const scope = mainScope(state);
  closeThinking(scope, at);
  state.fold.openContent = null;
  state.blocks.push(block);
}

function mainScope(state: RunTimeline): Scope {
  return { blocks: state.blocks, fold: state.fold };
}

function subScope(state: RunTimeline, key: string): Scope | null {
  const index = state.fold.subagentIndexByKey[key];
  const block = index === undefined ? undefined : (state.blocks[index] as SubagentBlock);
  if (!block) return null;
  state.fold.subFolds[key] ??= { openThinking: null, openContent: null, toolPaths: {} };
  return { blocks: block.blocks, fold: state.fold.subFolds[key], subKey: key };
}

// ---------------------------------------------------------------------------
// Tools
// ---------------------------------------------------------------------------
function applyTool(state: RunTimeline, scope: Scope, event: RawEvent) {
  const type = event.type;
  const id = String(event.toolCallId ?? '');
  const paths = scope.fold.toolPaths;
  const itemAt = (p: ToolPath) => (scope.blocks[p.block] as ThinkingBlock | undefined)?.items[p.item];

  if (type === 'TOOL_CALL_START') {
    const name = String(event.toolCallName ?? id ?? 'tool');
    const existing = id ? paths[id] : undefined;
    const retool = state.fold.pendingRetool;
    state.fold.pendingRetool = null;
    // A HITL resume can repeat the same call id, or re-run an approved tool under a fresh id:
    // either way it folds back into the stalled step so params, approval and result read as one.
    const target =
      existing ?? (retool && retool.name === name && retool.subKey === scope.subKey ? retool : undefined);
    if (target) {
      const item = itemAt(target);
      if (item?.kind === 'tool') {
        item.argsStale = true;
        item.state = 'input-streaming';
        item.startedAt = ts(event) ?? item.startedAt;
        if (id) paths[id] = { block: target.block, item: target.item };
        return;
      }
    }
    const block = ensureThinking(state, scope, ts(event));
    block.items.push({
      kind: 'tool',
      id: id || nextId(state, 'tool'),
      name,
      argsText: '',
      state: 'input-streaming',
      startedAt: ts(event),
    });
    if (id)
      paths[id] = { block: scope.fold.openThinking ?? scope.blocks.length - 1, item: block.items.length - 1 };
    return;
  }
  const path = id ? paths[id] : undefined;
  const item = path ? itemAt(path) : undefined;
  if (!item || item.kind !== 'tool') return;
  if (type === 'TOOL_CALL_ARGS') {
    if (item.argsStale) {
      item.argsText = '';
      item.argsStale = false;
    }
    item.argsText += String(event.delta ?? '');
  } else if (type === 'TOOL_CALL_END') {
    if (item.state === 'input-streaming') item.state = 'input-available';
  } else if (type === 'TOOL_CALL_RESULT') {
    const chunk = String(event.content ?? '');
    item.state = event.error ? 'output-error' : 'output-available';
    item.result = item.result ? `${item.result}\n\n${chunk}` : chunk;
    item.resultTruncated = Boolean(event.truncated) || item.resultTruncated;
    item.endedAt = ts(event);
  }
}

// ---------------------------------------------------------------------------
// HITL
// ---------------------------------------------------------------------------
function pushInterrupt(state: RunTimeline, value: unknown, subagentId?: string): Approval | null {
  const v = rec(value);
  const wrapped = v.interrupt;
  const wrappedId = rec(wrapped).id;
  const id = String(wrappedId ?? nextId(state, 'hitl'));
  if (state.interrupts.some((i) => i.id === id)) return null;
  const approval: Approval = {
    kind: 'hitl',
    id,
    threadId: String(v.thread_id ?? id),
    content: wrapped,
    status: 'pending',
    subagentId,
  };
  const questions = askUserQuestions(wrapped);
  if (questions.length) approval.questions = questions;
  state.interrupts.push(approval);
  return approval;
}

/** Bind an approval to the resultless tool step(s) it gates (one per action, name-matched). */
function bindToTools(block: ThinkingBlock, approval: Approval): boolean {
  if (approval.questions) return false;
  const actions = hitlActionRequests(approval.content);
  const wanted = actions.length ? actions : [{ toolName: undefined }];
  const candidates = block.items
    .map((item, i) => ({ item, i }))
    .filter(
      ({ item }) =>
        item.kind === 'tool' &&
        item.state !== 'output-available' &&
        item.state !== 'output-error' &&
        !item.approval,
    )
    .map(({ i }) => i);
  if (!candidates.length) return false;
  const used = new Set<number>();
  let bound = false;
  wanted.forEach((action, actionIndex) => {
    let pick = candidates.find(
      (ci) => !used.has(ci) && (!action.toolName || (block.items[ci] as ToolStep).name === action.toolName),
    );
    if (pick === undefined) pick = candidates.find((ci) => !used.has(ci));
    if (pick === undefined) return;
    used.add(pick);
    (block.items[pick] as ToolStep).approval = {
      ...approval,
      actionIndex: wanted.length > 1 ? actionIndex : undefined,
    };
    bound = true;
  });
  return bound;
}

function placeInterrupt(state: RunTimeline, scope: Scope, approval: Approval, at?: number) {
  if (approval.questions) {
    ensureThinking(state, scope, at).items.push(approval);
    return;
  }
  const open = scope.fold.openThinking;
  const block =
    open !== null
      ? (scope.blocks[open] as ThinkingBlock)
      : ([...scope.blocks].reverse().find((b) => b.kind === 'thinking') as ThinkingBlock | undefined);
  if (block && bindToTools(block, approval)) return;
  ensureThinking(state, scope, at).items.push(approval);
}

function resolveInterrupt(state: RunTimeline, value: Record<string, unknown>) {
  const interruptId = value.interrupt_id != null ? String(value.interrupt_id) : null;
  const targetId = interruptId ?? state.interrupts.find((i) => i.status === 'pending')?.id;
  if (!targetId) return;
  const decision = value.decision;
  const status: ApprovalStatus = decision === 'reject' || decision === 'expired' ? 'rejected' : 'approved';
  const reason = str(value.reason) ?? null;
  const decisions = Array.isArray(value.decisions)
    ? value.decisions.map((d) => ({
        status: (rec(d).decision === 'reject' ? 'rejected' : 'approved') as ApprovalStatus,
        reason: str(rec(d).reason) ?? null,
      }))
    : undefined;
  const answers = askUserAnswers(value.answers);

  const top = state.interrupts.find((i) => i.id === targetId);
  if (top) Object.assign(top, { status, reason, ...(answers ? { answers } : {}) });

  const resolveIn = (block: ThinkingBlock, blockIndex: number, subKey?: string) => {
    block.items.forEach((item, itemIndex) => {
      if (item.kind === 'hitl' && item.id === targetId) {
        Object.assign(item, { status, reason, ...(answers ? { answers } : {}) });
      } else if (item.kind === 'tool' && item.approval?.id === targetId) {
        const idx = item.approval.actionIndex;
        const outcome =
          decisions && typeof idx === 'number' && decisions[idx] ? decisions[idx] : { status, reason };
        item.approval = { ...item.approval, status: outcome.status, reason: outcome.reason };
        if (outcome.status === 'approved') {
          state.fold.pendingRetool = { block: blockIndex, item: itemIndex, name: item.name, subKey };
        } else {
          item.state = 'output-error';
          item.result = outcome.reason ? `Rejected: ${outcome.reason}` : 'Rejected by the reviewer';
        }
      }
    });
  };
  state.blocks.forEach((block, bi) => {
    if (block.kind === 'thinking') resolveIn(block, bi);
    else if (block.kind === 'subagent') {
      const key = Object.entries(state.fold.subagentIndexByKey).find(([, v]) => v === bi)?.[0];
      block.blocks.forEach((sub, si) => sub.kind === 'thinking' && resolveIn(sub, si, key));
      if (block.status === 'awaiting_approval' && !hasPendingFor(state, key)) block.status = 'running';
    }
  });
}

function hasPendingFor(state: RunTimeline, key: string | undefined) {
  return state.interrupts.some((i) => i.status === 'pending' && i.subagentId === key);
}

// ---------------------------------------------------------------------------
// Sub-agents
// ---------------------------------------------------------------------------
function ensureSubagent(state: RunTimeline, key: string, at?: number): SubagentBlock {
  const index = state.fold.subagentIndexByKey[key];
  if (index !== undefined) return state.blocks[index] as SubagentBlock;
  const block: SubagentBlock = {
    kind: 'subagent',
    id: nextId(state, 'sub'),
    taskId: key,
    status: 'pending',
    startedAt: at,
    blocks: [],
  };
  pushStandalone(state, block, at);
  state.fold.subagentIndexByKey[key] = state.blocks.length - 1;
  const nested = state.fold.nestedTasks?.[key];
  if (nested) applyNestedTask(block, nested);
  return block;
}

/** A nested sub-agent learns who delegated to it and what it was asked. */
function applyNestedTask(
  block: SubagentBlock,
  nested: { parentKey: string; type?: string; description?: string },
) {
  block.parentTaskId ||= nested.parentKey;
  block.type ||= nested.type;
  block.label ||= toTitleCase(nested.type);
  block.description ||= nested.description;
}

/** A sub-agent returned (`SUBAGENT_COMPLETED`, top level or inside its parent's envelope). */
function applySubagentCompleted(state: RunTimeline, v: Record<string, unknown>, at?: number) {
  const taskId = str(v.task_id);
  const ns = Array.isArray(v.namespace) ? v.namespace.map(String).join(' / ') : '';
  const key = (ns && state.fold.namespaceToKey[ns]) || taskId;
  const index = key ? state.fold.subagentIndexByKey[key] : undefined;
  if (index === undefined) return;
  const block = state.blocks[index] as SubagentBlock;
  block.status = v.status === 'error' || v.status === 'failed' ? 'failed' : 'done';
  block.startedAt = num(v.started_at) ?? block.startedAt;
  block.endedAt = num(v.ended_at) ?? at;
}

function applySubagentEvent(state: RunTimeline, value: unknown, at?: number) {
  const v = rec(value);
  const taskId = str(v.task_id);
  const inner = rec(v.event) as RawEvent;
  if (!taskId) return;
  const namespace = Array.isArray(v.namespace) ? v.namespace.map(String).join(' / ') : '';
  let key = namespace ? state.fold.namespaceToKey[namespace] : undefined;
  if (!key) {
    key = taskId;
    if (namespace) state.fold.namespaceToKey[namespace] = key;
  }
  const block = ensureSubagent(state, key, at);
  if (!block.spawned) {
    block.spawned = true;
    block.startedAt ??= at;
  }
  if (block.status === 'pending') block.status = 'running';
  block.namespace ||= namespace || undefined;
  block.label ||= toTitleCase(block.type);
  const scope = subScope(state, key);
  if (!scope || typeof inner.type !== 'string') return;
  const innerAt = ts(inner) ?? at;
  const type = inner.type;
  if (type === 'CUSTOM') {
    const value = rec(inner.value);
    if (inner.name === HITL_INTERRUPT) {
      const approval = pushInterrupt(state, inner.value, key);
      if (approval) {
        block.status = 'awaiting_approval';
        placeInterrupt(state, scope, approval, innerAt);
      }
    } else if (inner.name === TASK_SUBAGENT) {
      // This sub-agent delegated in turn: remember the call for the nested block it starts.
      const nestedId = str(value.task_id);
      if (!nestedId || nestedId === key) return;
      const nested = {
        parentKey: key,
        type: str(value.subagent_type),
        description: str(value.description),
      };
      state.fold.nestedTasks = { ...(state.fold.nestedTasks ?? {}), [nestedId]: nested };
      const nestedIndex = state.fold.subagentIndexByKey[nestedId];
      if (nestedIndex !== undefined) applyNestedTask(state.blocks[nestedIndex] as SubagentBlock, nested);
    } else if (inner.name === SUBAGENT_COMPLETED) {
      applySubagentCompleted(state, value, innerAt);
    } else if (inner.name === BEFORE_AGENT_EVENT) {
      const prompt = str(value.message);
      if (prompt) {
        block.prompt ||= prompt;
        block.description ||= prompt;
      }
    }
    return;
  }
  applyCore(state, scope, inner, innerAt);
}

// ---------------------------------------------------------------------------
// The event switch
// ---------------------------------------------------------------------------
/** Thinking, tools and text: shared by the main run and every sub-agent. */
function applyCore(state: RunTimeline, scope: Scope, event: RawEvent, at?: number): boolean {
  const type = event.type as string;
  if (type === 'THINKING_START') {
    ensureThinking(state, scope, at);
    return true;
  }
  if (type === 'THINKING_TEXT_MESSAGE_CONTENT') {
    const block = ensureThinking(state, scope, at);
    const delta = String(event.delta ?? '');
    const last = block.items[block.items.length - 1];
    // Providers stream reasoning in small deltas: keep growing the last thought until a tool
    // step interrupts it (magenticx stores each step; we merge for readable prose).
    if (last?.kind === 'thought') last.text += delta;
    else block.items.push({ kind: 'thought', id: nextId(state, 'thought'), text: delta });
    return true;
  }
  if (type === 'THINKING_END') {
    closeThinking(scope, at);
    return true;
  }
  if (type.startsWith('TOOL_CALL_')) {
    applyTool(state, scope, event);
    return true;
  }
  if (TEXT_DELTA.has(type)) {
    ensureContent(state, scope, at).text += String(event.delta ?? '');
    return true;
  }
  if (type === 'TEXT_MESSAGE_START') {
    closeThinking(scope, at);
    return true;
  }
  if (type === 'TEXT_MESSAGE_END') {
    scope.fold.openContent = null;
    return true;
  }
  return false;
}

function applyCustom(state: RunTimeline, name: string, value: unknown, event: RawEvent) {
  const at = ts(event);
  const v = rec(value);
  switch (name) {
    case HITL_INTERRUPT: {
      const approval = pushInterrupt(state, value);
      if (!approval) return;
      // The orchestrator's `task` call itself gated: its sub-agent card waits on it.
      if (hitlActionRequests(approval.content).some((a) => a.toolName === 'task')) {
        state.blocks.forEach((b) => {
          if (b.kind === 'subagent' && !b.spawned && b.status === 'pending') b.status = 'awaiting_approval';
        });
      }
      placeInterrupt(state, mainScope(state), approval, at);
      return;
    }
    case BRIDGE_HITL_RESOLVED:
      resolveInterrupt(state, v);
      return;
    case SUBAGENT_EVENT:
      applySubagentEvent(state, value, at);
      return;
    case TASK_SUBAGENT: {
      const taskId = str(v.task_id);
      if (!taskId) return;
      const block = ensureSubagent(state, taskId, at);
      block.type ||= str(v.subagent_type);
      block.label ||= toTitleCase(str(v.subagent_type));
      block.description ||= str(v.description);
      return;
    }
    case SUBAGENT_COMPLETED:
      applySubagentCompleted(state, v, at);
      return;
    case PRESENT_ARTIFACT: {
      const filename = str(v.filename);
      if (!filename) return;
      pushStandalone(
        state,
        {
          kind: 'artifact',
          id: nextId(state, 'artifact'),
          artifactId: str(v.artifact_id) ?? filename,
          path: str(v.path) ?? filename,
          filename,
          title: str(v.title),
          summary: str(v.summary),
          mime: str(v.mime),
        },
        at,
      );
      return;
    }
    case PLAN_SNAPSHOT:
    case 'plan_snapshot': {
      const items = Array.isArray(v.items) ? v.items : Array.isArray(v.todos) ? v.todos : null;
      if (!items) return;
      const next = items
        .map((it) => rec(it))
        .filter((it) => str(it.content))
        .map((it) => ({ content: String(it.content), status: str(it.status) ?? 'pending' }));
      state.planTimings = advancePlanTimings(state.plan, state.planTimings, next, planSnapshotTime(v, event));
      state.plan = next;
      return;
    }
    case TOKEN_USAGE: {
      const u = state.usage ?? { inputTokens: 0, outputTokens: 0, modelCalls: 0 };
      u.inputTokens += num(v.input_tokens) ?? 0;
      u.outputTokens += num(v.output_tokens) ?? 0;
      u.modelCalls += 1;
      u.model = str(v.model) ?? u.model;
      u.contextTokens = num(v.context_tokens) ?? u.contextTokens;
      u.contextWindow = num(v.context_window) ?? u.contextWindow;
      u.contextPercent = num(v.context_percent) ?? u.contextPercent;
      state.usage = u;
      return;
    }
    case SOURCES:
    case 'sources': {
      const list = Array.isArray(v.sources) ? v.sources : [];
      const parsed: Source[] = [];
      for (const s of list) {
        const r = rec(s);
        const url = str(r.url);
        if (!url || !/^https?:\/\//i.test(url)) continue;
        const source = { id: String(r.id ?? url), url, title: str(r.title), snippet: str(r.snippet) };
        state.sources[source.id] = source;
        parsed.push(source);
      }
      const callId = str(v.tool_call_id);
      const path = callId ? state.fold.toolPaths[callId] : undefined;
      const item = path
        ? (state.blocks[path.block] as ThinkingBlock | undefined)?.items[path.item]
        : undefined;
      if (item?.kind === 'tool') item.sources = [...(item.sources ?? []), ...parsed];
      return;
    }
    case TASK_LAUNCHED: {
      const taskId = str(v.task_id);
      if (!taskId) return;
      pushStandalone(
        state,
        {
          kind: 'task_ref',
          id: nextId(state, 'task'),
          taskId,
          name: str(v.name) ?? 'Background task',
          description: str(v.description),
          action: v.action === 'update' ? 'update' : 'start',
        },
        at,
      );
      return;
    }
    case TASK_SETTLED_INLINE: {
      const taskId = str(v.task_id);
      if (!taskId) return;
      pushStandalone(
        state,
        {
          kind: 'task_settled',
          id: nextId(state, 'settled'),
          taskId,
          name: str(v.name) ?? 'Background task',
          status: str(v.status) ?? 'success',
        },
        at,
      );
      return;
    }
    default:
  }
}

function applyEvent(state: RunTimeline, event: RawEvent) {
  const type = event.type;
  if (typeof type !== 'string') return;
  if (type === 'CUSTOM') {
    if (typeof event.name === 'string') applyCustom(state, event.name, event.value, event);
    return;
  }
  // Some emitters send custom events as their own top-level type.
  if (type === TASK_LAUNCHED || type === TASK_SETTLED_INLINE) {
    applyCustom(state, type, event.value ?? event, event);
    return;
  }
  applyCore(state, mainScope(state), event, ts(event));
}

/** Fold new events into a timeline (seq-deduped). Returns a new object; the input is not mutated. */
export function reduceTimelineEvents(state: RunTimeline, events: RawEvent[]): RunTimeline {
  if (!events.length || state.terminal) return state;
  const next = structuredClone(state);
  for (const event of events) {
    if (!event || typeof event !== 'object') continue;
    const seq = typeof event.seq === 'number' ? event.seq : null;
    if (seq !== null && seq <= next.lastSeq) continue;
    try {
      applyEvent(next, event);
    } catch {
      // A malformed event never takes the timeline down.
    }
    if (seq !== null) next.lastSeq = seq;
  }
  return next;
}

/** The run ended: close open blocks, settle running sub-agents, mark pending approvals moot. */
export function finalizeTimeline(state: RunTimeline, status: TerminalStatus): RunTimeline {
  if (state.terminal && state.terminalStatus === status) return state;
  const next = structuredClone(state);
  next.terminal = true;
  next.terminalStatus = status;
  closeThinking(mainScope(next));
  next.fold.openContent = null;
  for (const block of next.blocks) {
    if (block.kind === 'thinking') block.endedAt ??= block.startedAt;
    if (block.kind === 'subagent' && !['done', 'failed', 'cancelled'].includes(block.status)) {
      block.status = !block.spawned
        ? 'pending'
        : status === 'completed'
          ? 'done'
          : status === 'failed'
            ? 'failed'
            : 'cancelled';
    }
    if (block.kind === 'thinking' || block.kind === 'subagent') {
      const items =
        block.kind === 'thinking'
          ? [block]
          : block.blocks.filter((b): b is ThinkingBlock => b.kind === 'thinking');
      for (const t of items) {
        for (const item of t.items) {
          if (
            item.kind === 'tool' &&
            (item.state === 'input-streaming' || item.state === 'input-available')
          ) {
            item.state = status === 'completed' && !item.approval ? 'output-available' : 'output-error';
          }
        }
      }
    }
  }
  return next;
}

export const TERMINAL_STATUSES = new Set(['completed', 'cancelled', 'failed']);

/** A whole stored log → timeline (hydration of a finished or live message). */
export function foldTimeline(
  events: RawEvent[] | null | undefined,
  opts: { status?: string | null; content?: string | null; thinking?: string[] | null } = {},
): RunTimeline {
  let timeline = reduceTimelineEvents(createTimeline(), events ?? []);
  // A message with no event log (older or seeded): show its stored thinking + content.
  if (!timeline.blocks.length && (opts.content || opts.thinking?.length)) {
    timeline = structuredClone(timeline);
    if (opts.thinking?.length) {
      timeline.blocks.push({
        kind: 'thinking',
        id: 'legacy-think',
        items: opts.thinking.map((text, i) => ({ kind: 'thought', id: `legacy-thought-${i}`, text })),
      });
    }
    if (opts.content) timeline.blocks.push({ kind: 'content', id: 'legacy-text', text: opts.content });
  }
  const status = opts.status ?? null;
  if (status && TERMINAL_STATUSES.has(status))
    timeline = finalizeTimeline(timeline, status as TerminalStatus);
  return timeline;
}

export function pendingInterrupts(timeline: RunTimeline | null | undefined): Approval[] {
  return timeline?.interrupts.filter((i) => i.status === 'pending') ?? [];
}

/** The answer text of a timeline (all content blocks of the main run). */
export function timelineText(timeline: RunTimeline | null | undefined): string {
  return (
    timeline?.blocks
      .filter((b): b is ContentBlock => b.kind === 'content')
      .map((b) => b.text)
      .join('\n\n') ?? ''
  );
}

/** Whether the agent has visibly started (any block or pending approval). */
export function hasAgentSignal(timeline: RunTimeline | null | undefined): boolean {
  return Boolean(timeline && (timeline.blocks.length > 0 || timeline.interrupts.length > 0));
}
