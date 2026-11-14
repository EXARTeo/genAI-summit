/*
 * Written here rather than taken from a library: a port of magenticx's conversation row
 * (ChatSidebar.tsx `SidebarListRow` + `renderConversationRow`). Title only, nudged right on hover;
 * the open chat wears a filled highlight with a short accent bar that glides between rows; a chat
 * whose agent is working shows a spinner at the row end in place of the "⋯" menu; rename is inline.
 */
import { motion, useReducedMotion } from 'framer-motion';
import { Archive, ArrowRight, Loader2, MoreHorizontal, Pencil, Pin, PinOff, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { cn } from '@/shared/lib/utils';
import { DropdownMenu } from '@/shared/ui';
import { chatRoutes } from '../../lib/routes';
import { conversationTitle } from '../../lib/sidebarList';
import { ROW_GLIDE, SIDEBAR_ROW_LAYOUT_ID, rowMotion } from '../../lib/sidebarMotion';
import type { ConversationSummary } from '../../lib/types';

const ROW =
  'group/row relative flex min-h-8 w-full items-center rounded-xl px-2.5 py-1 pr-8 text-left text-muted outline-none transition-colors duration-150 [@media(hover:hover)]:hover:bg-hover [@media(hover:hover)]:hover:text-text active:bg-hover-strong focus-visible:bg-hover focus-visible:text-text focus-visible:ring-2 focus-visible:ring-ring aria-[current=page]:font-medium aria-[current=page]:text-text';

const ROW_END =
  'absolute right-1 top-1/2 z-[2] grid size-7 -translate-y-1/2 place-items-center rounded-lg text-muted';

export interface ConversationRowProps {
  conversation: ConversationSummary;
  index: number;
  active: boolean;
  /** The agent is working in this chat (a live run, a streaming message or background tasks). */
  working: boolean;
  renaming: boolean;
  onStartRename: () => void;
  onCancelRename: () => void;
  onRename: (title: string) => Promise<unknown>;
  onTogglePin: () => void;
  onArchive: () => void;
  onDelete: () => void;
  onNavigate?: () => void;
  /** Where the row menu opens: beside the row on the desktop rail, below it in the narrow drawer. */
  menuSide?: 'right' | 'bottom';
}

function RenameBox({
  initial,
  onCancel,
  onSubmit,
}: {
  initial: string;
  onCancel: () => void;
  onSubmit: (title: string) => Promise<unknown>;
}) {
  const [draft, setDraft] = useState(initial);
  const [busy, setBusy] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus and select the title; a press anywhere else cancels (magenticx).
  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    });
    const onPointerDown = (e: PointerEvent) => {
      if (boxRef.current && e.target instanceof Node && boxRef.current.contains(e.target)) return;
      onCancel();
    };
    window.addEventListener('pointerdown', onPointerDown);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('pointerdown', onPointerDown);
    };
  }, [onCancel]);

  const submit = async () => {
    const title = draft.trim();
    if (!title || busy) return;
    setBusy(true);
    try {
      await onSubmit(title);
    } catch {
      setBusy(false);
    }
  };

  return (
    <div
      ref={boxRef}
      className="flex min-h-8 w-full items-center gap-1.5 rounded-xl border border-border/60 bg-background/80 py-0.5 pl-2 pr-0.5"
    >
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            void submit();
          }
          if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            onCancel();
          }
        }}
        aria-label="Chat title"
        placeholder="Rename chat"
        spellCheck={false}
        maxLength={200}
        className="h-6 min-w-0 flex-1 bg-transparent text-[13px] font-medium text-text outline-none placeholder:text-muted"
      />
      <button
        type="button"
        aria-label="Confirm rename"
        onClick={() => void submit()}
        disabled={!draft.trim() || busy}
        className="grid size-6 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground shadow-sm transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
      >
        {busy ? <Loader2 className="size-3 animate-spin" /> : <ArrowRight className="size-3.5" />}
      </button>
    </div>
  );
}

export function ConversationRow({
  conversation: c,
  index,
  active,
  working,
  renaming,
  onStartRename,
  onCancelRename,
  onRename,
  onTogglePin,
  onArchive,
  onDelete,
  onNavigate,
  menuSide = 'right',
}: ConversationRowProps) {
  const reduceMotion = useReducedMotion();
  const title = conversationTitle(c);

  return (
    <motion.li data-motion="row" className="group/item relative" {...rowMotion(reduceMotion, index)}>
      {renaming ? (
        <RenameBox initial={title} onCancel={onCancelRename} onSubmit={onRename} />
      ) : (
        <Link
          to={chatRoutes.conversation(c.id)}
          onClick={onNavigate}
          aria-current={active ? 'page' : undefined}
          aria-busy={working || undefined}
          className={ROW}
        >
          {active && (
            // The open chat's highlight, shared across rows and sections so it glides to the
            // newly opened row; a short accent bar marks it.
            <motion.span
              layoutId={SIDEBAR_ROW_LAYOUT_ID}
              aria-hidden
              data-indicator="row"
              className="absolute inset-0 z-0 rounded-xl bg-hover"
              transition={reduceMotion ? { duration: 0 } : ROW_GLIDE}
            >
              <span className="absolute left-[3px] top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-primary" />
            </motion.span>
          )}
          <span className="relative z-[1] truncate text-[13px] transition-transform duration-200 ease-out motion-safe:[@media(hover:hover)]:group-hover/row:translate-x-[3px]">
            {title}
          </span>
        </Link>
      )}
      {!renaming &&
        (working ? (
          <span role="status" aria-label="Agent is working" className={ROW_END}>
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          </span>
        ) : (
          <DropdownMenu
            side={menuSide}
            align={menuSide === 'right' ? 'start' : 'end'}
            sideOffset={menuSide === 'right' ? 8 : 4}
            className="w-48"
            trigger={
              <button
                type="button"
                aria-label="Chat actions"
                className={cn(
                  ROW_END,
                  'outline-none transition-[opacity,color] duration-150 hover:text-text focus-visible:text-text focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:text-text data-[state=open]:opacity-100 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:focus-visible:opacity-100 [@media(hover:hover)]:group-focus-within/item:opacity-100 [@media(hover:hover)]:group-hover/item:opacity-100',
                )}
              >
                <MoreHorizontal className="size-3.5" />
              </button>
            }
            items={[
              { label: 'Rename', icon: <Pencil />, onSelect: onStartRename },
              {
                label: c.isPinned ? 'Unpin' : 'Pin',
                icon: c.isPinned ? <PinOff /> : <Pin />,
                onSelect: onTogglePin,
              },
              { label: 'Archive', icon: <Archive />, onSelect: onArchive },
              { type: 'separator' },
              { label: 'Delete', icon: <Trash2 />, danger: true, onSelect: onDelete },
            ]}
          />
        ))}
    </motion.li>
  );
}
