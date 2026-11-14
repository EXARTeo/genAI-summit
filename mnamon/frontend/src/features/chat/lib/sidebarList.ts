/**
 * Pure logic behind the conversation list (magenticx `ChatSidebar.tsx` + `search/SearchPanel.tsx`):
 * Pinned and Chats are two disjoint lists (newest pin first; the rest most recent first, paged),
 * search results are grouped by kind in a fixed order.
 */
import type { ConversationSummary, Page, SearchResult } from './types';

const time = (iso?: string | null) => (iso ? new Date(iso).getTime() || 0 : 0);

/** A row's title: its own, else the last message, else a placeholder (magenticx's fallback). */
export function conversationTitle(c: Pick<ConversationSummary, 'title' | 'lastMessage'>): string {
  return c.title?.trim() || c.lastMessage?.trim() || 'Untitled chat';
}

/** Pinned chats, newest pin first (ties: most recently updated first). */
export function sortPinned(list: readonly ConversationSummary[]): ConversationSummary[] {
  return [...list]
    .filter((c) => c.isPinned && !c.isArchived)
    .sort((a, b) => time(b.pinnedAt) - time(a.pinnedAt) || time(b.updated_at) - time(a.updated_at));
}

/**
 * The Chats section from its loaded pages: one row per id (a chat that moved to the top between
 * two page loads appears once), never a pinned or archived one (they live in their own lists).
 */
export function flattenPages(pages: readonly Page<ConversationSummary>[] | undefined): ConversationSummary[] {
  const seen = new Set<string>();
  const out: ConversationSummary[] = [];
  for (const page of pages ?? []) {
    for (const c of page.items) {
      if (seen.has(c.id) || c.isPinned || c.isArchived) continue;
      seen.add(c.id);
      out.push(c);
    }
  }
  return out;
}

/** The next page number to load, or undefined when the last loaded page was the last one. */
export function nextPageParam(last: Page<unknown>, loaded: number, size: number): number | undefined {
  const page = last.page ?? loaded;
  if (last.pages != null) return page < last.pages ? page + 1 : undefined;
  return last.items.length >= size ? page + 1 : undefined;
}

/** Whether a scrolled list is close enough to its end to page in more. */
export function isNearBottom(
  el: Pick<HTMLElement, 'scrollTop' | 'clientHeight' | 'scrollHeight'>,
  threshold = 16,
): boolean {
  return el.scrollTop + el.clientHeight >= el.scrollHeight - threshold;
}

export const SEARCH_GROUPS: { kind: SearchResult['kind']; label: string }[] = [
  { kind: 'conversation', label: 'Chats' },
  { kind: 'message', label: 'Messages' },
  { kind: 'file', label: 'Files' },
];

/** Search results grouped by kind (Chats, Messages, Files), empty groups dropped, order kept. */
export function groupSearchResults(
  results: readonly SearchResult[],
): { kind: SearchResult['kind']; label: string; items: SearchResult[] }[] {
  return SEARCH_GROUPS.map((g) => ({ ...g, items: results.filter((r) => r.kind === g.kind) })).filter(
    (g) => g.items.length > 0,
  );
}

/** A search snippet as plain text: markdown emphasis, code ticks, heading and list marks dropped. */
export function plainSnippet(text: string | null | undefined): string {
  return (text ?? '')
    .replace(/(\*\*|__|`+)/g, '')
    .replace(/(^|\s)[*_](\S[^*_]*?)[*_](?=\s|$|[.,;:!?])/g, '$1$2')
    .replace(/^\s*(#{1,6}|[-*+]|\d+\.)\s+/gm, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/** A recent conversation as a search result, for the panel's default "Recent chats" list. */
export function asSearchResult(c: ConversationSummary): SearchResult {
  return {
    kind: 'conversation',
    id: c.id,
    conversationId: c.id,
    agentSlug: c.agentSlug,
    title: conversationTitle(c),
    snippet: c.lastMessage ?? null,
    updatedAt: c.updated_at,
  };
}
