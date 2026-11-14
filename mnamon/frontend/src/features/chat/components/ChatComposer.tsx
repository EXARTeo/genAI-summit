/**
 * The composer (magenticx `ChatInputBar.tsx` + `ComposerPanel.tsx` + `SlashCommandMenu.tsx`):
 * an auto-growing textarea (Enter sends, Shift+Enter breaks the line), files by button, paste or
 * drop (with read progress and a preview on click), the slash-command menu, the "Discussing"
 * chip for a chat about a system or audit, the agent picker for a new chat, and Send / Stop.
 */
import { ArrowUp, Bot, ChevronDown, Loader2, Paperclip, Square, Target, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { cn } from '@/shared/lib/utils';
import { DropdownMenu, IconButton, Tooltip } from '@/shared/ui';
import type { Composer } from '../hooks/useComposer';
import { formatBytes, previewKind } from '../lib/attachments';
import { matchCommands, type SlashCommand } from '../lib/slashCommands';
import type { AgentManifest } from '../lib/types';
import { useChatUi } from './chatContext';
import { fileIconFor } from './message_parts/MessageAttachments';

export interface ComposerSubject {
  label: string;
  /** Only a new chat can drop its subject. */
  onClear?: () => void;
}

interface ChatComposerProps {
  composer: Composer;
  onSubmit: () => void;
  onStop: () => void;
  onCommand: (command: SlashCommand) => void;
  running: boolean;
  sending: boolean;
  hasConversation: boolean;
  placeholder?: string;
  subject?: ComposerSubject | null;
  agents?: AgentManifest[];
  agent?: AgentManifest | null;
  onAgentChange?: (agent: AgentManifest) => void;
  queued?: string | null;
  autoFocus?: boolean;
}

export function ChatComposer({
  composer,
  onSubmit,
  onStop,
  onCommand,
  running,
  sending,
  hasConversation,
  placeholder = 'Ask about a system, a finding or an article…',
  subject,
  agents = [],
  agent,
  onAgentChange,
  queued,
  autoFocus,
}: ChatComposerProps) {
  const { openPreview } = useChatUi();
  const { draft, setDraft, attachments, addFiles, remove, canSend } = composer;
  const textarea = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const commands = useMemo(() => matchCommands(draft, hasConversation), [draft, hasConversation]);
  const [highlight, setHighlight] = useState(0);
  useEffect(() => setHighlight(0), [commands?.length]);

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
        setDraft('');
        return;
      }
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (canSend && !sending) onSubmit();
    }
  };

  const showAgentPicker = !hasConversation && agents.length > 1 && agent && onAgentChange;

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
        <div className="mb-2 flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-1.5 text-xs text-muted">
          <Loader2 className="size-3 animate-spin" /> Queued: “{queued.slice(0, 80)}” is sent when the answer
          ends
        </div>
      )}

      <div
        className={cn(
          'rounded-2xl border border-border bg-surface shadow-card transition-[border-color,box-shadow] duration-150 focus-within:border-primary/50 focus-within:ring-2 focus-within:ring-primary/15',
        )}
      >
        {(subject || attachments.length > 0) && (
          <div className="flex flex-wrap items-center gap-1.5 px-3 pt-2.5">
            {subject && (
              <span className="inline-flex items-center gap-1.5 rounded-md bg-primary/10 py-0.5 pl-1.5 pr-1 text-xs text-primary">
                <Target className="size-3" />
                <span>
                  Discussing: <span className="font-medium">{subject.label}</span>
                </span>
                {subject.onClear && (
                  <button
                    type="button"
                    onClick={subject.onClear}
                    aria-label="Stop discussing this"
                    className="grid size-4 place-items-center rounded hover:bg-primary/15"
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
                  className="group relative inline-flex max-w-[14rem] items-center gap-1.5 overflow-hidden rounded-md border border-border bg-surface-muted py-1 pl-1.5 pr-1 text-xs"
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
          placeholder={placeholder}
          aria-label="Message"
          className="block max-h-60 min-h-[44px] w-full resize-none bg-transparent px-4 pb-1 pt-3 text-sm leading-6 outline-none placeholder:text-muted"
        />

        <div className="flex items-center gap-1 px-2 pb-2">
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
          <IconButton
            label="Attach files"
            icon={<Paperclip />}
            size="icon-sm"
            onClick={() => fileInput.current?.click()}
          />
          {showAgentPicker && (
            <DropdownMenu
              align="start"
              trigger={
                <button
                  type="button"
                  className="inline-flex h-7 items-center gap-1.5 rounded-lg px-2 text-xs text-muted transition-colors hover:bg-surface-muted hover:text-text"
                >
                  <Bot className="size-3.5" />
                  {agent.name}
                  <ChevronDown className="size-3" />
                </button>
              }
              items={agents.map((a) => ({
                label: (
                  <span className="flex flex-col">
                    <span>{a.name}</span>
                    {a.description && <span className="text-2xs text-muted">{a.description}</span>}
                  </span>
                ),
                checked: a.slug === agent.slug,
                onSelect: () => onAgentChange(a),
              }))}
            />
          )}
          {!showAgentPicker && agent && (
            <span className="inline-flex h-7 items-center gap-1.5 px-2 text-xs text-muted">
              <Bot className="size-3.5" />
              {agent.name}
            </span>
          )}
          <span className="ml-auto hidden text-2xs text-muted sm:inline">
            <kbd className="font-sans">/</kbd> commands · <kbd className="font-sans">Shift ⏎</kbd> new line
          </span>
          {running ? (
            <Tooltip content="Stop (Esc)">
              <button
                type="button"
                onClick={onStop}
                aria-label="Stop"
                className="ml-2 grid size-8 place-items-center rounded-lg bg-text text-background transition-opacity hover:opacity-90"
              >
                <Square className="size-3 fill-current" />
              </button>
            </Tooltip>
          ) : null}
          {(!running || draft.trim()) && (
            <button
              type="button"
              onClick={onSubmit}
              disabled={!canSend || sending}
              aria-label={running ? 'Queue message' : 'Send'}
              className="ml-1 grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground transition-[background-color,opacity] hover:bg-primary/90 disabled:bg-surface-muted disabled:text-muted"
            >
              {sending ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
