/**
 * The message list (magenticx `ChatBody.tsx` + `lib/streamScroll.ts`): the visible branch in a
 * `max-w-3xl` column. While an answer streams the view keeps the question near the top until the
 * answer reaches the bottom edge, then rides the bottom (a spacer below the content keeps that
 * reachable). Any upward wheel, drag or scroll detaches it; coming back near the bottom
 * re-attaches. A round jump-to-latest button shows when the view is away from the bottom.
 */
import { ArrowDown } from 'lucide-react';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { cn } from '@/shared/lib/utils';
import type { ChatController } from '../hooks/useChat';
import { siblingInfo } from '../lib/branches';
import { isActiveRun } from '../lib/runState';
import {
  findStreamAnchor,
  JUMP_BUTTON_DISTANCE,
  RESTICK_DISTANCE,
  streamScrollTarget,
} from '../lib/streamScroll';
import { AssistantMessage, UserMessage } from './ChatMessage';

/** A scroll event within this many px of a value we just wrote is our own echo, not the user. */
const ECHO_PX = 2;
const UNPIN_SCROLL_DELTA = 3;
const UNPIN_TOUCH_DELTA = 6;

export function ChatBody({ chat }: { chat: ChatController }) {
  const scroller = useRef<HTMLDivElement>(null);
  const column = useRef<HTMLDivElement>(null);
  const spacer = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const lastWritten = useRef(-1);
  const lastTop = useRef(0);
  const lastHeight = useRef(0);
  const touchY = useRef(0);
  const [away, setAway] = useState(false);
  const { path, messages, activeRun, runView, sending } = chat;
  const busy = sending || Boolean(activeRun);
  const tail = activeRun ? `${activeRun.id}:${activeRun.timeline.lastSeq}:${activeRun.status}` : '';

  const last = path[path.length - 1];
  const liveReplyId = last && last.sender !== 'user' && isActiveRun(runView(last)) ? last.id : null;
  const anchorId = busy ? findStreamAnchor(path, liveReplyId) : null;

  const write = useCallback((top: number) => {
    const el = scroller.current;
    if (!el) return;
    lastWritten.current = top;
    el.scrollTop = top;
  }, []);

  const setSpacer = (px: number) => {
    if (spacer.current) spacer.current.style.height = `${Math.max(0, Math.round(px))}px`;
  };

  /** Keep the stream in view: anchor the question, then ride the bottom. */
  const follow = useCallback(() => {
    const el = scroller.current;
    const col = column.current;
    if (!el || !col || !stick.current) return;
    const contentBottom = col.offsetTop + col.offsetHeight;
    let anchorTop: number | null = null;
    if (anchorId) {
      const node = col.querySelector<HTMLElement>(`[data-message-id="${CSS.escape(anchorId)}"]`);
      if (node) anchorTop = node.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop;
    }
    const { target, spacer: room } = streamScrollTarget({
      viewportHeight: el.clientHeight,
      scrollTop: el.scrollTop,
      heading: el.scrollTop,
      contentBottom,
      anchorTop,
      hold: true,
    });
    setSpacer(room);
    if (Math.abs(el.scrollTop - target) > 1) write(target);
    // Attached to the stream: the view is where it should be, no jump button.
    setAway(false);
  }, [anchorId, write]);

  const distance = () => {
    const el = scroller.current;
    return el ? el.scrollHeight - el.scrollTop - el.clientHeight : 0;
  };

  // A send, edit or retry starts a run: follow it, wherever the view was.
  // Run finished: nothing moves. The spacer keeps exactly the room the view needs where it is.
  const wasBusy = useRef(false);
  useLayoutEffect(() => {
    const was = wasBusy.current;
    wasBusy.current = busy;
    if (busy && !was) stick.current = true;
    if (busy || !was) return;
    const el = scroller.current;
    const col = column.current;
    if (!el || !col) return;
    setSpacer(el.scrollTop + el.clientHeight - (col.offsetTop + col.offsetHeight));
    setAway(distance() > JUMP_BUTTON_DISTANCE);
  }, [busy]);

  // New content (a message, a streamed token, a status change) while attached.
  useLayoutEffect(() => {
    if (busy) follow();
    else if (stick.current) {
      const el = scroller.current;
      if (el) write(el.scrollHeight);
    }
  }, [path.length, tail, busy, follow, write]);

  // Size changes that are not renders of this list (an image loading, the composer shrinking).
  useEffect(() => {
    const el = scroller.current;
    const col = column.current;
    if (!busy || !el || !col || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => follow());
    observer.observe(el);
    observer.observe(col);
    return () => observer.disconnect();
  }, [busy, follow]);

  // A conversation opens at its end.
  useLayoutEffect(() => {
    stick.current = true;
    setSpacer(0);
    setAway(false);
    const el = scroller.current;
    if (el) write(el.scrollHeight);
  }, [chat.detail?.id, write]);

  const detach = () => {
    stick.current = false;
  };

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    const cur = el.scrollTop;
    const movedUp = lastTop.current - cur;
    lastTop.current = cur;
    // Content shrinking under the view (an edit replacing a long branch) makes the browser
    // clamp the view up: that is not the user scrolling away.
    const shrank = el.scrollHeight < lastHeight.current;
    lastHeight.current = el.scrollHeight;
    if (Math.abs(cur - lastWritten.current) < ECHO_PX) return;
    const gap = distance();
    setAway(gap > JUMP_BUTTON_DISTANCE);
    if (movedUp > UNPIN_SCROLL_DELTA && !shrank) detach();
    else if (gap <= RESTICK_DISTANCE) stick.current = true;
  };

  const jump = () => {
    const el = scroller.current;
    if (!el) return;
    stick.current = true;
    setAway(false);
    lastWritten.current = el.scrollHeight - el.clientHeight;
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  };

  return (
    <div className="relative min-h-0 flex-1 overflow-hidden">
      <div
        ref={scroller}
        onScroll={onScroll}
        onWheel={(e) => {
          if (e.deltaY < -1) detach();
        }}
        onTouchStart={(e) => {
          touchY.current = e.touches[0]?.clientY ?? 0;
        }}
        onTouchMove={(e) => {
          const y = e.touches[0]?.clientY ?? 0;
          if (y - touchY.current > UNPIN_TOUCH_DELTA) detach();
          touchY.current = y;
        }}
        className="relative h-full overflow-y-auto"
        data-testid="chat-scroll"
      >
        <div ref={column} className="mx-auto w-full max-w-3xl space-y-4 p-3 md:space-y-6 md:p-6">
          {path.map((m) => {
            const siblings = siblingInfo(messages, m);
            const onBranch = (index: number) => chat.switchBranch(m, index);
            return (
              <div key={m.id} data-message-id={m.id} className="animate-[fade-in_200ms_ease-out]">
                {m.sender === 'user' ? (
                  <UserMessage
                    message={m}
                    siblings={siblings}
                    onBranch={onBranch}
                    busy={busy}
                    onEdit={(text) => chat.edit(m.id, text)}
                  />
                ) : (
                  <AssistantMessage
                    message={m}
                    run={runView(m)}
                    siblings={siblings}
                    onBranch={onBranch}
                    busy={busy}
                    onRetry={() => void chat.retry(m.id)}
                    onRate={(liked) => void chat.rate(m, liked)}
                  />
                )}
              </div>
            );
          })}
        </div>
        <div ref={spacer} aria-hidden style={{ height: 0 }} />
      </div>
      <button
        type="button"
        aria-label="Jump to latest message"
        title="Jump to latest message"
        tabIndex={away ? 0 : -1}
        onClick={jump}
        className={cn(
          'absolute bottom-4 left-1/2 z-20 grid size-10 -translate-x-1/2 place-items-center rounded-full',
          'border border-border/70 bg-background text-text shadow-pop',
          'transition-[opacity,transform,color] duration-300 ease-out hover:text-primary',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60',
          away
            ? 'translate-y-0 scale-100 opacity-100'
            : 'pointer-events-none translate-y-4 scale-90 opacity-0',
        )}
      >
        <ArrowDown className="size-5" aria-hidden />
      </button>
    </div>
  );
}
