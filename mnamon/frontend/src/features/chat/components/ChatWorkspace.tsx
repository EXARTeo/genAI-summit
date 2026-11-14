/**
 * The chat page (magenticx `pages/ChatView.tsx` + `app/WorkspaceShell` chat wiring): conversation
 * list, header, messages, and the composer slot, which a pending approval or the agent's questions
 * take over. Files can be dropped anywhere on the page. Shortcuts: Esc stops the answer,
 * Ctrl/⌘+Shift+O starts a new chat, Ctrl/⌘+Shift+S focuses the chat search.
 */
import { Archive, MoreHorizontal, Pin, PinOff, Plus, Sparkles, Target, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState, type DragEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useHotkey } from '@/shared/hooks/useHotkey';
import { cn } from '@/shared/lib/utils';
import { DropdownMenu, ErrorState, IconButton, Skeleton, toast } from '@/shared/ui';
import { useChat } from '../hooks/useChat';
import { useComposer } from '../hooks/useComposer';
import { useAgents, useChatSubject, useConversationActions } from '../hooks/useConversations';
import { chatRoutes } from '../lib/routes';
import { parseCommand, type SlashCommand } from '../lib/slashCommands';
import type { AgentManifest } from '../lib/types';
import { AskUserTakeover } from './AskUserTakeover';
import { AttachmentPreview } from './AttachmentPreview';
import { ChatBody } from './ChatBody';
import { ChatComposer } from './ChatComposer';
import { ChatUiContext, type PreviewTarget } from './chatContext';
import { HitlTakeover } from './HitlTakeover';

const SUGGESTIONS = [
  'Why did F-001 on the CV Screener indicate a gap?',
  'Which systems are affected by the Art. 10 guideline change?',
  'Ask me to clarify before you review a system',
];

export function ChatWorkspace({ conversationId }: { conversationId: string | null }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const agents = useAgents();
  const [agentSlug, setAgentSlug] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewTarget | null>(null);
  const [dragging, setDragging] = useState(false);
  const composer = useComposer();
  const actions = useConversationActions();

  const querySubject = { systemId: params.get('system'), auditId: params.get('audit') };
  const agentList = useMemo(() => agents.data ?? [], [agents.data]);

  // The chat's own agent and subject once it exists; the picker and the URL before that.
  const chatAgentPlaceholder: AgentManifest | null =
    agentList.find((a) => a.slug === agentSlug) ?? agentList.find((a) => a.default) ?? agentList[0] ?? null;
  const chat = useChat(conversationId, { agent: chatAgentPlaceholder, subject: querySubject });
  const detail = chat.detail;
  const subjectIds = detail ? { systemId: detail.systemId, auditId: detail.auditId } : querySubject;
  const subject = useChatSubject(subjectIds.systemId, subjectIds.auditId);
  const agent: AgentManifest | null = detail
    ? (agentList.find((a) => a.slug === (agentSlug ?? detail.agentSlug)) ?? {
        slug: detail.agentSlug,
        name: detail.agentName ?? detail.agentSlug,
      })
    : chatAgentPlaceholder;

  useEffect(() => {
    setAgentSlug(null);
    composer.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  const subjectLabel = useMemo(() => {
    if (!subjectIds.systemId && !subjectIds.auditId) return null;
    const name = subject.data?.systemName ?? subjectIds.systemId ?? '';
    return [name, subjectIds.auditId ? `audit ${subjectIds.auditId}` : null].filter(Boolean).join(' · ');
  }, [subject.data, subjectIds.systemId, subjectIds.auditId]);

  const runCommand = useCallback(
    (command: SlashCommand, arg = '') => {
      const id = detail?.id;
      switch (command.name) {
        case 'new':
          navigate(chatRoutes.root);
          return;
        case 'rename':
          if (id && arg) actions.rename.mutate({ id, title: arg });
          return;
        case 'pin':
          if (detail) actions.pin.mutate({ id: detail.id, pinned: !detail.isPinned });
          return;
        case 'archive':
          if (id)
            actions.archive.mutate({ id, archived: true }, { onSuccess: () => navigate(chatRoutes.root) });
          return;
        case 'retry': {
          const last = [...chat.path].reverse().find((m) => m.sender === 'ai');
          if (last) void chat.retry(last.id);
          return;
        }
        case 'stop':
          void chat.stop();
          return;
        case 'agent': {
          const found = agentList.find((a) => a.slug === arg || a.name.toLowerCase() === arg.toLowerCase());
          if (found) {
            setAgentSlug(found.slug);
            toast.success(`Next message goes to ${found.name}`);
          } else
            toast.error(
              arg ? `No agent called “${arg}”` : `Agents: ${agentList.map((a) => a.slug).join(', ')}`,
            );
          return;
        }
        case 'search':
          document.querySelector<HTMLInputElement>('input[aria-label="Search chats"]')?.focus();
          return;
        default:
      }
    },
    [detail, actions, navigate, chat, agentList],
  );

  const submit = useCallback(async () => {
    const parsed = parseCommand(composer.draft);
    if (parsed && composer.attachments.length === 0) {
      composer.setDraft('');
      runCommand(parsed.command, parsed.arg);
      return;
    }
    const ok = await chat.send({ text: composer.draft, attachments: composer.attachments });
    if (ok) composer.reset();
  }, [composer, chat, runCommand]);

  useHotkey('escape', () => chat.activeRun && void chat.stop(), true);
  useHotkey('mod+shift+o', () => navigate(chatRoutes.root), true);
  useHotkey(
    'mod+shift+s',
    () => document.querySelector<HTMLInputElement>('input[aria-label="Search chats"]')?.focus(),
    true,
  );

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) composer.addFiles(e.dataTransfer.files);
  };

  const pending = chat.pending[0] ?? null;
  const takeover = pending ? (
    pending.questions ? (
      <AskUserTakeover approval={pending} onAnswer={(answers) => chat.answer(pending, answers)} />
    ) : (
      <HitlTakeover
        approval={pending}
        pendingCount={chat.pending.length}
        onResolve={(d) => chat.decide(pending, d)}
      />
    )
  ) : null;

  const composerEl = (
    <ChatComposer
      composer={composer}
      onSubmit={() => void submit()}
      onStop={() => void chat.stop()}
      onCommand={(c) => runCommand(c)}
      running={Boolean(chat.activeRun)}
      sending={chat.sending}
      hasConversation={Boolean(detail)}
      subject={
        subjectLabel
          ? { label: subjectLabel, onClear: detail ? undefined : () => setParams({}, { replace: true }) }
          : null
      }
      agents={agentList}
      agent={agent}
      onAgentChange={(a) => setAgentSlug(a.slug)}
      queued={chat.queued}
      autoFocus
    />
  );

  const empty = !conversationId;
  const notFound = chat.conversation.isError;

  return (
    <ChatUiContext.Provider
      value={{
        conversationId: detail?.id ?? null,
        systemId: subject.data?.systemId ?? subjectIds.systemId ?? null,
        systemName: subject.data?.systemName ?? null,
        openPreview: setPreview,
      }}
    >
      <div
        className="-mx-4 -my-6 flex h-[calc(var(--shell-viewport)-var(--topbar-height))] lg:-mx-8 lg:-my-8"
        onDragOver={(e) => {
          if (Array.from(e.dataTransfer.types).includes('Files')) {
            e.preventDefault();
            setDragging(true);
          }
        }}
        onDragLeave={(e) => {
          if (e.currentTarget === e.target) setDragging(false);
        }}
        onDrop={onDrop}
      >
        <section className={cn('relative flex min-w-0 flex-1 flex-col', dragging && 'chat-drop')}>
          <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4">
            <h1 className="min-w-0 truncate text-sm font-medium">
              {empty ? 'New chat' : (detail?.title ?? (chat.conversation.isPending ? '' : 'Chat'))}
            </h1>
            {detail && subjectLabel && subjectIds.systemId && (
              <Link
                to={`/systems/${encodeURIComponent(subjectIds.systemId)}`}
                className="hidden items-center gap-1 rounded-md px-1.5 py-0.5 text-2xs text-muted hover:bg-surface-muted hover:text-text sm:inline-flex"
              >
                <Target className="size-3" /> {subjectLabel}
              </Link>
            )}
            <div className="ml-auto flex items-center gap-1">
              {detail && (
                <DropdownMenu
                  trigger={<IconButton label="Chat options" icon={<MoreHorizontal />} size="icon-sm" />}
                  items={[
                    {
                      label: detail.isPinned ? 'Unpin' : 'Pin',
                      icon: detail.isPinned ? <PinOff /> : <Pin />,
                      onSelect: () => actions.pin.mutate({ id: detail.id, pinned: !detail.isPinned }),
                    },
                    {
                      label: 'Archive',
                      icon: <Archive />,
                      onSelect: () =>
                        actions.archive.mutate(
                          { id: detail.id, archived: true },
                          { onSuccess: () => navigate(chatRoutes.root) },
                        ),
                    },
                    { type: 'separator' },
                    {
                      label: 'Delete',
                      icon: <Trash2 />,
                      danger: true,
                      onSelect: () =>
                        actions.remove.mutate(detail.id, { onSuccess: () => navigate(chatRoutes.root) }),
                    },
                  ]}
                />
              )}
              <IconButton
                label="New chat (Ctrl+Shift+O)"
                icon={<Plus />}
                size="icon-sm"
                onClick={() => navigate(chatRoutes.root)}
              />
            </div>
          </header>

          {notFound ? (
            <div className="grid flex-1 place-items-center p-6">
              <ErrorState title="This chat is not available" error={chat.conversation.error} />
            </div>
          ) : empty ? (
            <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-4 pb-[10vh]">
              <div className="w-full max-w-2xl space-y-6">
                <div className="text-center">
                  <div className="mx-auto mb-3 grid size-10 place-items-center rounded-xl border border-border bg-surface text-primary">
                    <Sparkles className="size-4" />
                  </div>
                  <h2 className="text-xl font-semibold">
                    {subjectLabel
                      ? `What about ${subject.data?.systemName ?? subjectLabel}?`
                      : 'What should we look into?'}
                  </h2>
                  <p className="mt-1 text-sm text-muted">
                    Every tool call, sub-agent and approval shows up as it happens, and is traced.
                  </p>
                </div>
                {composerEl}
                <div className="grid gap-2 sm:grid-cols-3">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => composer.setDraft(s)}
                      className="rounded-lg border border-border bg-surface p-3 text-left text-xs text-muted transition-colors hover:border-primary/40 hover:text-text"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : chat.conversation.isPending ? (
            <div className="mx-auto w-full max-w-3xl space-y-6 px-4 pt-8">
              <Skeleton className="ml-auto h-10 w-2/3 rounded-2xl" />
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : (
            <>
              <ChatBody chat={chat} />
              <div className="mx-auto w-full max-w-3xl px-4 pb-4">
                {takeover ?? composerEl}
                <p className="mt-1.5 text-center text-2xs text-muted">
                  Agents can be wrong. Check the evidence before you act on it.
                </p>
              </div>
            </>
          )}

          {dragging && (
            <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center">
              <div className="rounded-xl border border-border bg-surface px-4 py-3 text-sm shadow-pop">
                Drop files to attach them
              </div>
            </div>
          )}
        </section>
      </div>
      <AttachmentPreview target={preview} onClose={() => setPreview(null)} />
    </ChatUiContext.Provider>
  );
}
