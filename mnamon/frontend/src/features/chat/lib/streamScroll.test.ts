import { describe, expect, it } from 'vitest';
import {
  BOTTOM_BREATHING_ROOM,
  findStreamAnchor,
  SCROLL_PADDING_TOP,
  streamScrollTarget,
} from './streamScroll';
import type { MessageOut } from './types';

const msg = (id: string, sender: 'user' | 'ai', parent: string | null = null) =>
  ({ id, sender, parentMessageId: parent }) as MessageOut;

describe('streamScrollTarget', () => {
  const base = { viewportHeight: 600, scrollTop: 0, heading: 0 };

  it('holds the question near the top while the answer is short', () => {
    const r = streamScrollTarget({ ...base, contentBottom: 1200, anchorTop: 1000 });
    expect(r.target).toBe(1000 - SCROLL_PADDING_TOP);
    // The spacer makes the anchored position reachable.
    expect(r.target + 600).toBeLessThanOrEqual(1200 + r.spacer);
  });

  it('rides the bottom once the answer reaches the bottom edge', () => {
    const r = streamScrollTarget({ ...base, contentBottom: 2000, anchorTop: 1000 });
    expect(r.target).toBe(2000 + BOTTOM_BREATHING_ROOM - 600);
    expect(r.spacer).toBe(BOTTOM_BREATHING_ROOM);
  });

  it('never moves back up with hold, and stays put without an anchor', () => {
    const held = streamScrollTarget({
      ...base,
      scrollTop: 1500,
      heading: 1500,
      contentBottom: 1800,
      anchorTop: 1000,
      hold: true,
    });
    expect(held.target).toBe(1500);
    const free = streamScrollTarget({
      ...base,
      scrollTop: 300,
      heading: 300,
      contentBottom: 1800,
      anchorTop: null,
    });
    expect(free.target).toBe(300);
  });
});

describe('findStreamAnchor', () => {
  it('anchors the just-sent question', () => {
    expect(findStreamAnchor([msg('u1', 'user')], null)).toBe('u1');
  });

  it("anchors the live reply's question", () => {
    expect(findStreamAnchor([msg('u1', 'user'), msg('a1', 'ai', 'u1')], 'a1')).toBe('u1');
  });

  it('ignores a settled last answer and an empty path', () => {
    expect(findStreamAnchor([msg('u1', 'user'), msg('a1', 'ai', 'u1')], null)).toBeNull();
    expect(findStreamAnchor([], 'a1')).toBeNull();
  });
});
