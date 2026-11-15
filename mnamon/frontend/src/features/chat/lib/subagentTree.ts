/**
 * Which sub-agent delegated to which (port of magenticx `features/inference/timeline.ts`
 * `resolveSubagentParents` / `subagentTree` / `subagentRunStatus`). Every sub-agent is a top-level
 * block of the run timeline (a nested one's events arrive in an envelope of their own); this says
 * which of them belong inside which.
 */
import type { RunTimeline, SubagentBlock, SubagentStatus } from './timeline';

const NAMESPACE_SEPARATOR = ' / ';

/**
 * The parent of each sub-agent block, by index into `blocks` (-1: the main agent's own, or a
 * parent that is not among `blocks`). The namespace path is the primary link: a nested
 * sub-agent's LangGraph namespace extends its parent's, so the parent is the block with the
 * longest namespace that is a strict prefix of it (acyclic by construction). The `task` call the
 * fold saw inside a parent (`parentTaskId`) is the fallback when a namespace is missing, accepted
 * only if it does not close a loop.
 */
export function resolveSubagentParents(blocks: SubagentBlock[]): number[] {
  const segments = blocks.map((block) =>
    block.namespace ? block.namespace.split(NAMESPACE_SEPARATOR) : null,
  );
  const indexByTask = new Map(blocks.map((block, index) => [block.taskId, index]));
  const parents = blocks.map((_, index) => {
    const own = segments[index];
    let best = -1;
    let bestLength = 0;
    if (own) {
      segments.forEach((candidate, other) => {
        if (other === index || !candidate || candidate.length >= own.length) return;
        if (candidate.length <= bestLength) return;
        if (candidate.every((part, i) => part === own[i])) {
          best = other;
          bestLength = candidate.length;
        }
      });
    }
    return best;
  });
  blocks.forEach((block, index) => {
    if (parents[index] !== -1 || !block.parentTaskId) return;
    const parent = indexByTask.get(block.parentTaskId);
    if (parent === undefined || parent === index) return;
    // Walk up from the would-be parent; reaching this block would be a loop.
    let cursor = parent;
    for (let guard = 0; cursor !== -1 && guard <= blocks.length; guard += 1) {
      if (cursor === index) return;
      cursor = parents[cursor];
    }
    parents[index] = parent;
  });
  return parents;
}

export interface SubagentTree {
  /** The sub-agent blocks with no parent among the timeline's blocks. */
  roots: SubagentBlock[];
  /** Each block's own sub-agents, in the order they appear. */
  childrenOf: (block: SubagentBlock) => SubagentBlock[];
  /** Whether a block sits under another block of the same timeline. */
  isNested: (block: SubagentBlock) => boolean;
}

/** A timeline's sub-agents as a tree: what the inline cards nest and the agent map lists. */
export function subagentTree(timeline: Pick<RunTimeline, 'blocks'> | null | undefined): SubagentTree {
  const blocks = (timeline?.blocks ?? []).filter(
    (block): block is SubagentBlock => block.kind === 'subagent',
  );
  const parents = resolveSubagentParents(blocks);
  const children = new Map<SubagentBlock, SubagentBlock[]>();
  const nested = new Set<SubagentBlock>();
  const roots: SubagentBlock[] = [];
  blocks.forEach((block, index) => {
    const parent = parents[index];
    if (parent === -1) {
      roots.push(block);
      return;
    }
    nested.add(block);
    const list = children.get(blocks[parent]) ?? [];
    list.push(block);
    children.set(blocks[parent], list);
  });
  return {
    roots,
    childrenOf: (block) => children.get(block) ?? [],
    isNested: (block) => nested.has(block),
  };
}

/**
 * The status a sub-agent shows, or null when it is not shown at all. `live` is whether the run
 * still streams to this view. A run that is not live and not terminal (a reload mid-run) never
 * shows a sub-agent as working: it waits on an approval when one is pending, otherwise it
 * stopped. An unspawned block (a `task` call before it ran) shows only while it can still run.
 */
export function subagentRunStatus(
  block: SubagentBlock,
  timeline: Pick<RunTimeline, 'terminal' | 'terminalStatus' | 'interrupts'>,
  live: boolean,
): SubagentStatus | null {
  const pending = timeline.interrupts.some((item) => item.status === 'pending');
  if (!block.spawned) {
    if (timeline.terminal) return null;
    if (block.status === 'awaiting_approval' && pending) return 'awaiting_approval';
    return live && block.status !== 'done' && block.status !== 'failed' ? 'pending' : null;
  }
  const status = block.status ?? 'running';
  if (status !== 'running' && status !== 'pending') return status;
  if (live && !timeline.terminal) return 'running';
  if (timeline.terminal) return timeline.terminalStatus === 'completed' ? 'done' : 'cancelled';
  return pending ? 'awaiting_approval' : 'cancelled';
}
