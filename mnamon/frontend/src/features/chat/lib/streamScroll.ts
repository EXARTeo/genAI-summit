/**
 * The pure geometry of ChatBody's "keep the stream in view" scrolling (port of magenticx
 * `features/chat/lib/streamScroll.ts`), apart from the component so the rules can be tested
 * without a layout engine.
 */
import type { MessageOut } from './types';

/** Gap kept above the question while it sits anchored at the top during streaming. */
export const SCROLL_PADDING_TOP = 24;
/** Gap kept below the newest line so it never butts against the composer. */
export const BOTTOM_BREATHING_ROOM = 48;
/** Distance from the bottom at which the jump-to-latest button shows. */
export const JUMP_BUTTON_DISTANCE = 160;
/** Within this distance of the bottom a detached view re-attaches to the stream. */
export const RESTICK_DISTANCE = 36;

/**
 * Where the view should sit while a reply streams, and how tall the spacer below the content
 * must be (all in scroll coordinates). The question is held near the top while the answer is
 * short; once the newest line would reach the bottom edge the view rides the bottom instead,
 * with breathing room. The two meet without a step.
 *
 * `heading` is where the view is (or is going). With no question to anchor the view stays
 * there; with `hold` it never moves back up from there either. The spacer keeps both the target
 * and the current `scrollTop` reachable, so the browser never clamps the view up a step.
 */
export function streamScrollTarget(m: {
  viewportHeight: number;
  scrollTop: number;
  heading: number;
  contentBottom: number;
  anchorTop: number | null;
  hold?: boolean;
}): { target: number; spacer: number } {
  const target =
    m.anchorTop === null
      ? Math.max(0, m.heading)
      : Math.max(
          0,
          m.anchorTop - SCROLL_PADDING_TOP,
          m.contentBottom + BOTTOM_BREATHING_ROOM - m.viewportHeight,
          m.hold ? m.heading : 0,
        );
  const lowest = Math.max(target, m.scrollTop);
  return {
    target,
    spacer: Math.max(BOTTOM_BREATHING_ROOM, lowest + m.viewportHeight - m.contentBottom),
  };
}

/**
 * The question the streaming reply answers: the turn the view anchors to. Only a live turn
 * counts: the user's own message when it is last (sent, the run not there yet), or the parent of
 * the reply being written when that reply is the newest message.
 */
export function findStreamAnchor(path: MessageOut[], liveReplyId: string | null): string | null {
  const last = path[path.length - 1];
  if (!last) return null;
  if (last.sender === 'user') return last.id;
  if (liveReplyId && last.id === liveReplyId) return last.parentMessageId ?? last.id;
  return null;
}
