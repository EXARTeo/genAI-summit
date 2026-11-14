/**
 * The composer (magenticx `ChatInputBar.tsx` + `ComposerPanel.tsx` + `SlashCommandMenu.tsx`):
 * one rounded card with an auto-growing textarea ("Message Copilot…"; Enter sends, Shift+Enter
 * breaks the line), files by "+", paste or drop (with read progress and a preview on click), the
 * slash-command menu, the "Discussing" chip for a chat about a system or audit, and one round
 * action button: Send, Stop while the agent answers, or Queue when something is typed meanwhile.
 * magenticx's travelling glow border is left out (no glows here): a hairline that firms up on
 * focus instead. The agent picker lives in the chat header.
 */
import { ArrowUp, Loader2, Plus, Square, Target, X } from 'lucide-react';
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';
import { cn } from '@/shared/lib/utils';
import { Tooltip } from '@/shared/ui';
import type { Composer } from '../hooks/useComposer';
import { formatBytes, previewKind } from '../lib/attachments';
import { matchCommands, type SlashCommand } from '../lib/slashCommands';
import { useChatUi } from './chatContext';
import { fileIconFor } from './message_parts/MessageAttachments';

export interface ComposerSubject {
  label: string;
  /** Only a new chat can drop its subject. */
  onClear?: () => void;
}

export interface ChatComposerHandle {
  focus: () => void;
  openFiles: () => void;
}

interface ChatComposerProps {
  composer: Composer;
  onSubmit: () => void;
  onStop: () => void;
  onCommand: (command: SlashCommand) => void;
  running: boolean;
  sending: boolean;
  hasConversation: boolean;
  /** Names the agent in the placeholder ("Message Copilot…"). */
  agentName?: string | null;
  placeholder?: string;
  subject?: ComposerSubject | null;
  queued?: string | null;
  autoFocus?: boolean;
}

const ROUND_TOOL =
  'grid size-9 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-hover hover:text-text active:bg-hover-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60';

export const ChatComposer = forwardRef<ChatComposerHandle, ChatComposerProps>(function ChatComposer(
  {
    composer,
    onSubmit,
    onStop,
    onCommand,
    running,
    sending,
    hasConversation,
    agentName,
    placeholder,
    subject,
    queued,
    autoFocus,
  },
  ref,
) {
  const { openPreview } = useChatUi();
  const { draft, setDraft, attachments, addFiles, remove, canSend } = composer;
  const textarea = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const commands = useMemo(() => matchCommands(draft, hasConversation), [draft, hasConversation]);
  const [highlight, setHighlight] = useState(0);
  useEffect(() => setHighlight(0), [commands?.length]);

  useImperativeHandle(
    ref,
    () => ({
      focus: () => textarea.current?.focus(),
      openFiles: () => fileInput.current?.click(),
    }),
    [],
  );

  // Auto-grow up to ~10 lines.
  useEffect(() => {
    const el = textarea.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  }, [draft]);

  useEffect(() => {
    if (autoFocus) textarea.current?.focus();
  }, [autoFocus]);

  const hasDraft = draft.trim().length > 0 || attachments.length > 0;
  // While the agent answers, a typed draft is queued (sent when the answer ends); with no
  // draft the button stops the answer.
  const queueOnSend = running && hasDraft;
  const action: 'send' | 'queue' | 'stop' = queueOnSend ? 'queue' : running ? 'stop' : 'send';

  const pick = (c: SlashCommand) => {
    if (c.arg) setDraft(`/${c.name} `);
    else {
      setDraft('');
      onCommand(c);
    }
    textarea.current?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (commands?.length) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        setHighlight((h) => (h + (e.key === 'ArrowDown' ? 1 : -1) + commands.length) % commands.length);
        return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        pick(commands[highlight]);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        setDraft('');
        return;
      }
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (canSend && !sending) onSubmit();
    }
  };

  const text = placeholder ?? (agentName ? `Message ${agentName}…` : 'Type a message…');

  return (
    <div className="relative">
      {commands && commands.length > 0 && (
        <div
          role="listbox"
          aria-label="Commands"
          className="absolute bottom-full left-0 z-20 mb-2 w-72 overflow-hidden rounded-xl border border-border bg-surface p-1 shadow-pop"
        >
          {commands.map((c, i) => (
            <button
              key={c.name}
              type="button"
              role="option"
              aria-selected={i === highlight}
              onMouseEnter={() => setHighlight(i)}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(c);
              }}
              className={cn(
                'flex w-full items-baseline gap-2 rounded-md px-2 py-1.5 text-left text-sm',
                i === highlight && 'bg-surface-muted',
              )}
            >
              <span className="font-mono text-xs text-primary">/{c.name}</span>
              {c.arg && <span className="font-mono text-2xs text-muted">{`<${c.arg}>`}</span>}
              <span className="ml-auto truncate text-xs text-muted">{c.description}</span>
            </button>
          ))}
        </div>
      )}

      {queued && (
        <div className="mb-2 flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-1.5 text-xs text-muted">
          <Loader2 className="size-3 animate-spin" /> Queued: “{queued.slice(0, 80)}” is sent when the answer
          ends
        </div>
      )}

      <div
        data-composer
        data-busy={running || undefined}
        className="rounded-[1.75rem] border border-border bg-surface shadow-card transition-[border-color,box-shadow] duration-150 focus-within:border-primary/35 focus-within:ring-[3px] focus-within:ring-primary/[0.07]"
      >
        {(subject || attachments.length > 0) && (
          <div className="flex flex-wrap items-center gap-1.5 px-4 pt-3">
            {subject && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 py-0.5 pl-2 pr-1 text-xs text-primary">
                <Target className="size-3" />
                <span>
                  Discussing: <span className="font-medium">{subject.label}</span>
                </span>
                {subject.onClear && (
                  <button
                    type="button"
                    onClick={subject.onClear}
                    aria-label="Stop discussing this"
                    className="grid size-4 place-items-center rounded-full hover:bg-primary/15"
                  >
                    <X className="size-3" />
                  </button>
                )}
              </span>
            )}
            {attachments.map((a) => {
              const Icon = fileIconFor(a);
              const ready = Boolean(a.dataB64);
              return (
                <span
                  key={a.key}
                  className="group relative inline-flex max-w-[14rem] items-center gap-1.5 overflow-hidden rounded-lg border border-border bg-surface-muted py-1 pl-1.5 pr-1 text-xs"
                >
                  <button
                    type="button"
                    className="flex min-w-0 items-center gap-1.5"
                    onClick={() =>
                      previewKind(a) !== 'unsupported' && openPreview({ kind: 'pending', attachment: a })
                    }
                    aria-label={`Preview ${a.name}`}
                  >
                    {ready ? (
                      <Icon className="size-3.5 shrink-0 text-muted" />
                    ) : (
                      <Loader2 className="size-3.5 shrink-0 animate-spin text-primary" />
                    )}
                    <span className="truncate">{a.name}</span>
                    <span className="shrink-0 text-2xs text-muted">{formatBytes(a.size)}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(a.key)}
                    aria-label={`Remove ${a.name}`}
                    className="grid size-4 shrink-0 place-items-center rounded text-muted hover:bg-surface hover:text-text"
                  >
                    <X className="size-3" />
                  </button>
                  {!ready && (
                    <span
                      className="absolute bottom-0 left-0 h-0.5 bg-primary transition-[width] duration-150"
                      style={{ width: `${Math.round(a.progress * 100)}%` }}
                      aria-hidden
                    />
                  )}
                </span>
              );
            })}
          </div>
        )}

        <textarea
          ref={textarea}
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onPaste={(e) => {
            const files = Array.from(e.clipboardData.files);
            if (files.length) {
              e.preventDefault();
              addFiles(files);
            }
          }}
          placeholder={text}
          aria-label="Message"
          aria-expanded={commands && commands.length > 0 ? true : undefined}
          className="block max-h-60 min-h-[48px] w-full resize-none bg-transparent px-5 pb-1 pt-3.5 text-base outline-none placeholder:text-muted"
        />

        <div className="flex items-center gap-2 px-3 pb-3">
          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files) addFiles(e.target.files);
              e.target.value = '';
            }}
          />
          <Tooltip content="Attach files (Alt+A)">
            <button
              type="button"
              aria-label="Attach files"
              onClick={() => fileInput.current?.click()}
              className={ROUND_TOOL}
            >
              <Plus className="size-5" />
            </button>
          </Tooltip>
          <div className="ml-auto">
            <Tooltip
              content={
                action === 'stop' ? 'Stop (Esc)' : action === 'queue' ? 'Send when the answer ends' : 'Send'
              }
            >
              <button
                type="button"
                onClick={action === 'stop' ? onStop : onSubmit}
                disabled={action !== 'stop' && (!canSend || sending)}
                aria-label={action === 'stop' ? 'Stop' : action === 'queue' ? 'Queue message' : 'Send'}
                className={cn(
                  'grid size-9 place-items-center rounded-full transition-[background-color,color,opacity] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-2 focus-visible:ring-offset-surface',
                  action === 'stop'
                    ? 'bg-text text-background hover:opacity-90'
                    : 'bg-primary text-primary-foreground hover:bg-primary/90 disabled:bg-surface-muted disabled:text-muted',
                )}
              >
                {sending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : action === 'stop' ? (
                  <Square className="size-3.5 fill-current" />
                ) : (
                  <ArrowUp className="size-[18px]" />
                )}
              </button>
            </Tooltip>
          </div>
        </div>
      </div>
    </div>
  );
});
