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
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';
import { cn } from '@/shared/lib/utils';
import { classifyFile } from '@/shared/lib/files';
import { FileChip, ImageLightbox, Tooltip } from '@/shared/ui';
import type { Composer } from '../hooks/useComposer';
import type { PendingAttachment } from '../lib/attachments';
import { matchCommands, type SlashCommand } from '../lib/slashCommands';
import { useChatUi, type PreviewTarget } from './chatContext';

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
        {subject && (
          <div className="flex flex-wrap items-center gap-1.5 px-4 pt-3">
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
          </div>
        )}
        {attachments.length > 0 && (
          <ComposerAttachments attachments={attachments} onRemove={remove} onPreview={openPreview} />
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

/**
 * The files waiting to be sent (magenticx `ChatInputBar` attachment strip): one row that scrolls
 * sideways with fading edges, images first as 56 px thumbnails (open the lightbox), then file chips
 * (open the preview). Each chip shows its read progress, a failed read in red, and a remove button.
 */
function ComposerAttachments({
  attachments,
  onRemove,
  onPreview,
}: {
  attachments: PendingAttachment[];
  onRemove: (key: string) => void;
  onPreview: (target: PreviewTarget) => void;
}) {
  const ordered = useMemo(() => {
    const isImage = (a: PendingAttachment) => classifyFile(a).kind === 'image';
    return [...attachments.filter(isImage), ...attachments.filter((a) => !isImage(a))];
  }, [attachments]);

  // One object URL per image file, minted when the set of images changes (not on every progress
  // tick) and revoked with it.
  const imageFiles = attachments.filter((a) => classifyFile(a).kind === 'image');
  const imageKeys = imageFiles.map((a) => a.key).join('|');
  const [thumbs, setThumbs] = useState<Map<string, string>>(() => new Map());
  useEffect(() => {
    const created = new Map(imageFiles.map((a) => [a.key, URL.createObjectURL(a.file)] as const));
    setThumbs(created);
    return () => created.forEach((url) => URL.revokeObjectURL(url));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageKeys]);

  const images = ordered.filter((a) => thumbs.has(a.key));
  const [lightbox, setLightbox] = useState<number | null>(null);

  const strip = useRef<HTMLDivElement>(null);
  const [fade, setFade] = useState({ left: false, right: false });
  const measure = useCallback(() => {
    const el = strip.current;
    if (!el) return;
    setFade({
      left: el.scrollLeft > 2,
      right: el.scrollLeft + el.clientWidth < el.scrollWidth - 2,
    });
  }, []);
  useEffect(() => {
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [measure, ordered.length]);

  return (
    <div className="relative mx-3 mt-3 overflow-hidden rounded-2xl" data-testid="composer-attachments">
      <div ref={strip} onScroll={measure} className="overflow-x-auto pb-1 pr-6">
        <div className="flex min-w-max flex-nowrap items-center gap-2">
          {ordered.map((a) => {
            const thumb = thumbs.get(a.key);
            const imageIndex = images.findIndex((x) => x.key === a.key);
            const previewable = classifyFile(a).previewable;
            return (
              <FileChip
                key={a.key}
                variant="composer"
                name={a.name}
                mime={a.mime}
                size={a.size}
                thumbnail={thumb}
                progress={a.dataB64 ? 1 : a.progress}
                error={a.error}
                onOpen={
                  thumb
                    ? () => setLightbox(imageIndex)
                    : previewable
                      ? () => onPreview({ kind: 'pending', attachment: a })
                      : undefined
                }
                onRemove={() => onRemove(a.key)}
              />
            );
          })}
        </div>
      </div>
      {fade.left && (
        <div className="pointer-events-none absolute inset-y-0 left-0 w-5 bg-gradient-to-r from-surface to-transparent" />
      )}
      {fade.right && (
        <div className="pointer-events-none absolute inset-y-0 right-0 w-5 bg-gradient-to-l from-surface to-transparent" />
      )}
      <ImageLightbox
        images={images.map((a) => ({ src: thumbs.get(a.key) ?? '', name: a.name, mime: a.mime }))}
        index={lightbox}
        onIndexChange={setLightbox}
        onClose={() => setLightbox(null)}
      />
    </div>
  );
}
