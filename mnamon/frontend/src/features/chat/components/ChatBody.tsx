/**
 * The message list (magenticx `ChatBody.tsx` + `lib/streamScroll.ts`): the visible branch, kept
 * pinned to the bottom while an answer streams unless the user scrolled up, with a "jump to
 * latest" button then.
 */
import { ArrowDown } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { siblingInfo } from '../lib/branches';
import type { ChatController } from '../hooks/useChat';
import { AssistantMessage, UserMessage } from './ChatMessage';

export function ChatBody({ chat }: { chat: ChatController }) {
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const [away, setAway] = useState(false);
  const { path, messages, activeRun, runView, sending } = chat;
  const busy = sending || Boolean(activeRun);
  const tail = activeRun ? `${activeRun.id}:${activeRun.timeline.lastSeq}:${activeRun.status}` : '';

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    const gap = el.scrollHeight - el.scrollTop - el.clientHeight;
    stick.current = gap < 80;
    setAway(gap > 240);
  };

  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [path.length, tail]);

  // A conversation opens at its end.
  useEffect(() => {
    stick.current = true;
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chat.detail?.id]);

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={scroller} onScroll={onScroll} className="h-full overflow-y-auto" data-testid="chat-scroll">
        <div className="mx-auto flex max-w-3xl flex-col gap-7 px-4 pb-8 pt-6">
          {path.map((m, i) => {
            const siblings = siblingInfo(messages, m);
            const onBranch = (index: number) => chat.switchBranch(m, index);
            return m.sender === 'user' ? (
              <UserMessage
                key={m.id}
                message={m}
                siblings={siblings}
                onBranch={onBranch}
                busy={busy}
                onEdit={(text) => chat.edit(m.id, text)}
              />
            ) : (
              <AssistantMessage
                key={m.id}
                message={m}
                run={runView(m)}
                siblings={siblings}
                onBranch={onBranch}
                busy={busy}
                isLast={i === path.length - 1}
                onRetry={() => void chat.retry(m.id)}
                onRate={(liked) => void chat.rate(m, liked)}
              />
            );
          })}
        </div>
      </div>
      {away && (
        <button
          type="button"
          onClick={() => {
            const el = scroller.current;
            if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
          }}
          className="absolute bottom-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1 rounded-full border border-border bg-surface px-3 py-1 text-xs text-muted shadow-pop hover:text-text"
        >
          <ArrowDown className="size-3" /> Latest
        </button>
      )}
    </div>
  );
}
