import { describe, expect, it } from 'vitest';
import {
  asSearchResult,
  conversationTitle,
  flattenPages,
  groupSearchResults,
  isNearBottom,
  nextPageParam,
  plainSnippet,
  sortPinned,
} from './sidebarList';
import type { ConversationSummary, SearchResult } from './types';

const conv = (id: string, extra: Partial<ConversationSummary> = {}): ConversationSummary => ({
  id,
  agentSlug: 'assistant',
  title: id,
  isArchived: false,
  isPinned: false,
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
  ...extra,
});

describe('conversationTitle', () => {
  it('falls back to the last message, then a placeholder', () => {
    expect(conversationTitle({ title: '  Audit plan ', lastMessage: 'x' })).toBe('Audit plan');
    expect(conversationTitle({ title: ' ', lastMessage: 'Why is F-001 a gap?' })).toBe('Why is F-001 a gap?');
    expect(conversationTitle({ title: null, lastMessage: null })).toBe('Untitled chat');
  });
});

describe('sortPinned', () => {
  it('orders newest pin first and drops unpinned or archived chats', () => {
    const list = [
      conv('a', { isPinned: true, pinnedAt: '2026-11-02T00:00:00Z' }),
      conv('b', { isPinned: true, pinnedAt: '2026-11-05T00:00:00Z' }),
      conv('c'),
      conv('d', { isPinned: true, isArchived: true, pinnedAt: '2026-11-09T00:00:00Z' }),
    ];
    expect(sortPinned(list).map((c) => c.id)).toEqual(['b', 'a']);
  });
});

describe('flattenPages', () => {
  it('keeps page order, one row per id, never pinned or archived', () => {
    const pages = [
      { items: [conv('a'), conv('b'), conv('p', { isPinned: true })] },
      { items: [conv('b'), conv('c'), conv('z', { isArchived: true })] },
    ];
    expect(flattenPages(pages).map((c) => c.id)).toEqual(['a', 'b', 'c']);
    expect(flattenPages(undefined)).toEqual([]);
  });
});

describe('nextPageParam', () => {
  it('uses the page count when the server sends it', () => {
    expect(nextPageParam({ items: [], page: 1, pages: 3 }, 1, 30)).toBe(2);
    expect(nextPageParam({ items: [], page: 3, pages: 3 }, 3, 30)).toBeUndefined();
  });
  it('otherwise guesses from a full page', () => {
    expect(nextPageParam({ items: new Array(30).fill(0) }, 1, 30)).toBe(2);
    expect(nextPageParam({ items: [1, 2] }, 1, 30)).toBeUndefined();
  });
});

describe('isNearBottom', () => {
  it('fires within the threshold of the end', () => {
    expect(isNearBottom({ scrollTop: 485, clientHeight: 100, scrollHeight: 600 })).toBe(true);
    expect(isNearBottom({ scrollTop: 400, clientHeight: 100, scrollHeight: 600 })).toBe(false);
  });
});

describe('groupSearchResults', () => {
  it('groups by kind in Chats, Messages, Files order and drops empty groups', () => {
    const r = (kind: SearchResult['kind'], id: string): SearchResult => ({
      kind,
      id,
      conversationId: 'c1',
      title: id,
    });
    const groups = groupSearchResults([r('file', 'f1'), r('conversation', 'c1'), r('file', 'f2')]);
    expect(groups.map((g) => [g.label, g.items.map((i) => i.id)])).toEqual([
      ['Chats', ['c1']],
      ['Files', ['f1', 'f2']],
    ]);
  });
  it('turns a recent chat into a conversation result', () => {
    expect(asSearchResult(conv('a', { title: null, lastMessage: 'hello' }))).toMatchObject({
      kind: 'conversation',
      conversationId: 'a',
      title: 'hello',
    });
  });
});

describe('plainSnippet', () => {
  it('drops markdown marks', () => {
    expect(plainSnippet('**F-001 is a gap** because `ratio` is *low*.\n- next')).toBe(
      'F-001 is a gap because ratio is low. next',
    );
    expect(plainSnippet(null)).toBe('');
  });
});
