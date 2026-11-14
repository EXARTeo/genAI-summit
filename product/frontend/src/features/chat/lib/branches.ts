/**
 * Message branching (port of magenticx's branch handling in `handlers/messages.tsx` +
 * `lib/branchMemory.ts`). A conversation stores every branch: edits and retries are siblings
 * under the same parent. The UI shows one path, picked by a `selection` map
 * (parent id → chosen child id); without a choice the newest child wins.
 */
import type { MessageOut } from './types';

export const ROOT = '__root__';
export type BranchSelection = Record<string, string>;

const parentKey = (m: MessageOut) => m.parentMessageId ?? ROOT;
const byCreated = (a: MessageOut, b: MessageOut) => a.created_at.localeCompare(b.created_at);

export function childrenIndex(messages: MessageOut[]): Map<string, MessageOut[]> {
  const index = new Map<string, MessageOut[]>();
  for (const m of messages) {
    const key = parentKey(m);
    const list = index.get(key) ?? [];
    list.push(m);
    index.set(key, list);
  }
  for (const list of index.values()) list.sort(byCreated);
  return index;
}

/** The visible path from the root, following `selection` (newest child by default). */
export function visiblePath(messages: MessageOut[], selection: BranchSelection = {}): MessageOut[] {
  const index = childrenIndex(messages);
  const path: MessageOut[] = [];
  const seen = new Set<string>();
  let key = ROOT;
  for (;;) {
    const children = index.get(key);
    if (!children?.length) break;
    const chosen = children.find((c) => c.id === selection[key]) ?? children[children.length - 1];
    if (seen.has(chosen.id)) break;
    seen.add(chosen.id);
    path.push(chosen);
    key = chosen.id;
  }
  return path;
}

export interface SiblingInfo {
  index: number;
  count: number;
  ids: string[];
}

export function siblingInfo(messages: MessageOut[], message: MessageOut): SiblingInfo {
  const siblings = childrenIndex(messages).get(parentKey(message)) ?? [message];
  return {
    index: Math.max(
      0,
      siblings.findIndex((s) => s.id === message.id),
    ),
    count: siblings.length,
    ids: siblings.map((s) => s.id),
  };
}

/** Root → `messageId` ids (the `messagePath` a retry pins). */
export function pathTo(messages: MessageOut[], messageId: string): string[] {
  const byId = new Map(messages.map((m) => [m.id, m]));
  const out: string[] = [];
  let current = byId.get(messageId);
  const seen = new Set<string>();
  while (current && !seen.has(current.id)) {
    seen.add(current.id);
    out.unshift(current.id);
    current = current.parentMessageId ? byId.get(current.parentMessageId) : undefined;
  }
  return out;
}

/** A selection that makes `messageId` (and its ancestors) visible. */
export function selectionFor(
  messages: MessageOut[],
  messageId: string,
  base: BranchSelection = {},
): BranchSelection {
  const byId = new Map(messages.map((m) => [m.id, m]));
  const next = { ...base };
  for (const id of pathTo(messages, messageId)) {
    const m = byId.get(id);
    if (m) next[parentKey(m)] = m.id;
  }
  return next;
}

/** Select sibling `index` of `message`'s branch point. */
export function selectSibling(
  messages: MessageOut[],
  message: MessageOut,
  index: number,
  base: BranchSelection,
): BranchSelection {
  const { ids } = siblingInfo(messages, message);
  const id = ids[Math.max(0, Math.min(ids.length - 1, index))];
  return id ? { ...base, [parentKey(message)]: id } : base;
}
