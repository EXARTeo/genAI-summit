/**
 * The chat page (magenticx `pages/ChatView.tsx` + `app/WorkspaceShell` chat wiring): the header
 * (agent picker, subject, actions; the page puts it in the app's top bar), messages, and the
 * composer slot, which a pending approval or the agent's questions take over. A new chat is the
 * greeting with the composer centred. Files can be dropped anywhere on the page.
 * Shortcuts: Esc stops the answer, Ctrl/⌘+Shift+O starts a new chat, Ctrl/⌘+Shift+S focuses the
 * chat search, Alt+L focuses the composer, Alt+A attaches files, Alt+G opens the agent picker.
 */
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type DragEvent,
  type ReactNode,
} from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useHotkey } from '@/shared/hooks/useHotkey';
import { cn } from '@/shared/lib/utils';
import { ErrorState, LogoMark, Skeleton, toast } from '@/shared/ui';
import { useChat } from '../hooks/useChat';
import { useComposer } from '../hooks/useComposer';
import {
  useAgents,
  useChatSubject,
  useConversation,
  useConversationActions,
} from '../hooks/useConversations';
import { chatAgents, defaultChatAgent, isChatAgent } from '../lib/agents';
import { chatRoutes } from '../lib/routes';
import { parseCommand, type SlashCommand } from '../lib/slashCommands';
import type { AgentManifest } from '../lib/types';
import type { AgentPickerHandle } from './AgentPicker';
import { AskUserTakeover } from './AskUserTakeover';
import { AttachmentPreview } from './AttachmentPreview';
import { ChatBody } from './ChatBody';
import { ChatComposer, type ChatComposerHandle } from './ChatComposer';
import { ChatHeader } from './ChatHeader';
import { ChatUiContext, type PreviewTarget } from './chatContext';
import { HitlTakeover } from './HitlTakeover';

const SUGGESTIONS = [
  'Why did F-001 on the CV Screener indicate a gap?',
  'Which systems are affected by the Art. 10 guideline change?',
  'Ask me to clarify before you review a system',
];

/** The new chat's greeting, rotated like magenticx's welcome quotes ({agent} = the agent's name). */
export const GREETINGS = [
  'Ready when you are.',
  'What should we look into?',
  'Ask {agent} anything about your systems.',
  'Which finding should we dig into?',
  'Drop a file or paste a screenshot to start.',
  'Check a system against the AI Act.',
];
const GREETING_MS = 8000;

export const CHAT_DISCLAIMER = 'Agents can be wrong. Check the evidence before you act on it.';

function Greeting({ text }: { text: string }) {
  const reduce = useReducedMotion();
  return (
    <div className="flex h-16 flex-col justify-center md:h-[4.5rem]">
      <AnimatePresence mode="wait" initial={false}>
        <motion.h2
          key={text}
          initial={{ opacity: 0, y: reduce ? 0 : 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: reduce ? 0 : -4 }}
          transition={{ duration: 0.25, ease: 'easeOut' }}
          className="text-balance text-xl font-bold tracking-tight md:text-2xl"
        >
          {text}
        </motion.h2>
      </AnimatePresence>
    </div>
  );
}

function useRotatingGreeting(active: boolean, agentName: string) {
  const [index, setIndex] = useState(() => Math.floor(Math.random() * GREETINGS.length));
  useEffect(() => {
    if (!active) return;
    const id = setInterval(
      () => setIndex((i) => (i + 1 + Math.floor(Math.random() * (GREETINGS.length - 1))) % GREETINGS.length),
      GREETING_MS,
    );
    return () => clearInterval(id);
  }, [active]);
  return GREETINGS[index].replace('{agent}', agentName);
}

export function ChatWorkspace({
  conversationId,
  HeaderSlot,
}: {
  conversationId: string | null;
  /** Where the header goes (the page passes the app's top-bar slot); inline when left out. */
  HeaderSlot?: ComponentType<{ children: ReactNode }>;
}) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const agents = useAgents();
  const [agentSlug, setAgentSlug] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewTarget | null>(null);
  const [dragging, setDragging] = useState(false);
  const composer = useComposer();
  const actions = useConversationActions();
  const composerRef = useRef<ChatComposerHandle>(null);
  const pickerRef = useRef<AgentPickerHandle>(null);

  const querySubject = { systemId: params.get('system'), auditId: params.get('audit') };
  // Only chat-capable agents: a workflow such as the audit pipeline is never offered or picked.
  const agentList = useMemo(() => chatAgents(agents.data ?? []), [agents.data]);
  const picked = agentList.find((a) => a.slug === agentSlug) ?? null;
  const defaultAgent = useMemo(() => defaultChatAgent(agents.data ?? []), [agents.data]);
  const noChatAgent = agents.isError || (agents.isSuccess && !defaultAgent);
  const convSlug = useConversation(conversationId).data?.agentSlug;
  const convAgentUsable =
    !convSlug ||
    isChatAgent(agentList.find((a) => a.slug === convSlug) ?? { slug: convSlug, name: convSlug });

  // A new chat goes to the picked (else the default) agent; an open one keeps its own agent
  // unless one is picked in the header, or its agent can't chat (then the default takes over).
  const chat = useChat(conversationId, {
    agent: conversationId ? (picked ?? (convAgentUsable ? null : defaultAgent)) : (picked ?? defaultAgent),
    subject: querySubject,
  });
  const detail = chat.detail;
  const subjectIds = detail ? { systemId: detail.systemId, auditId: detail.auditId } : querySubject;
  const subject = useChatSubject(subjectIds.systemId, subjectIds.auditId);
  const detailSlug = detail?.agentSlug;
  const detailName = detail?.agentName;
  const chatAgent = useMemo<AgentManifest | null>(
    () =>
      detailSlug
        ? (agentList.find((a) => a.slug === detailSlug) ?? {
            slug: detailSlug,
            name: detailName ?? detailSlug,
          })
        : null,
    [agentList, detailSlug, detailName],
  );
  const agent = picked ?? (convAgentUsable ? chatAgent : null) ?? defaultAgent;
  const pickerAgents = useMemo(
    () =>
      chatAgent && isChatAgent(chatAgent) && !agentList.some((a) => a.slug === chatAgent.slug)
        ? [...agentList, chatAgent]
        : agentList,
    [agentList, chatAgent],
  );

  useEffect(() => {
    setAgentSlug(null);
    composer.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  const subjectLabel = useMemo(() => {
    if (!subjectIds.systemId && !subjectIds.auditId) return null;
    const name = subject.data?.systemName ?? subjectIds.systemId ?? '';
    return [name, subjectIds.auditId ? 'audit' : null].filter(Boolean).join(' · ');
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
          if (!arg) {
            pickerRef.current?.open();
            return;
          }
          const found = pickerAgents.find(
            (a) => a.slug === arg || a.name.toLowerCase() === arg.toLowerCase(),
          );
          if (found) {
            setAgentSlug(found.slug);
            toast.success(`Next message goes to ${found.name}`);
          } else toast.error(`No agent called “${arg}”`);
          return;
        }
        case 'search':
          document.querySelector<HTMLInputElement>('input[aria-label="Search chats"]')?.focus();
          return;
        default:
      }
    },
    [detail, actions, navigate, chat, pickerAgents],
  );

  const submit = useCallback(async () => {
    const parsed = parseCommand(composer.draft);
    if (parsed && composer.attachments.length === 0) {
      composer.setDraft('');
      runCommand(parsed.command, parsed.arg);
      return;
    }
    if (noChatAgent && !(conversationId && convAgentUsable)) {
      toast.error('No chat agent is available right now.');
      return;
    }
    const ok = await chat.send({ text: composer.draft, attachments: composer.attachments });
    if (ok) composer.reset();
  }, [composer, chat, runCommand, noChatAgent, conversationId, convAgentUsable]);

  useHotkey('escape', () => chat.activeRun && void chat.stop(), true);
  useHotkey('mod+shift+o', () => navigate(chatRoutes.root), true);
  useHotkey(
    'mod+shift+s',
    () => document.querySelector<HTMLInputElement>('input[aria-label="Search chats"]')?.focus(),
    true,
  );
  // magenticx's Alt shortcuts, matched on the physical key so other layouts work too.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      const run = {
        KeyL: () => composerRef.current?.focus(),
        KeyA: () => composerRef.current?.openFiles(),
        KeyG: () => pickerRef.current?.open(),
      }[e.code];
      if (!run) return;
      e.preventDefault();
      run();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) composer.addFiles(e.dataTransfer.files);
  };

  const empty = !conversationId;
  const notFound = chat.conversation.isError;
  const agentName = agent?.name ?? 'the agent';
  const rotating = useRotatingGreeting(empty && !subjectLabel, agentName);
  const greeting = subjectLabel ? `What about ${subject.data?.systemName ?? subjectLabel}?` : rotating;

  const pending = chat.pending[0] ?? null;
  const takeover = pending ? (
    pending.questions ? (
      <AskUserTakeover
        approval={pending}
        agentName={agent?.name}
        onAnswer={(answers) => chat.answer(pending, answers)}
      />
    ) : (
      <HitlTakeover
        approval={pending}
        pendingCount={chat.pending.length}
        onResolve={(d) => chat.decide(pending, d)}
      />
    )
  ) : null;

  const noAgentNotice = noChatAgent ? (
    <p
      role="alert"
      className="mb-2 rounded-xl border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-text"
    >
      {agents.isError
        ? 'The agents could not be loaded, so the chat cannot start a run. Try again in a moment.'
        : 'No chat agent is available yet. Audits run from the Audits page; the chat needs a chat agent.'}
    </p>
  ) : null;

  const composerEl = (
    <ChatComposer
      ref={composerRef}
      composer={composer}
      onSubmit={() => void submit()}
      onStop={() => void chat.stop()}
      onCommand={(c) => runCommand(c)}
      running={Boolean(chat.activeRun)}
      sending={chat.sending}
      hasConversation={Boolean(detail)}
      agentName={agent?.name}
      subject={
        subjectLabel
          ? { label: subjectLabel, onClear: detail ? undefined : () => setParams({}, { replace: true }) }
          : null
      }
      queued={chat.queued}
      autoFocus
    />
  );

  const header = (
    <ChatHeader
      ref={pickerRef}
      agents={pickerAgents}
      agent={agent}
      onAgentChange={(a) => setAgentSlug(a.slug)}
      title={empty ? null : detail?.title}
      subject={detail && subjectLabel ? { label: subjectLabel, systemId: subjectIds.systemId ?? null } : null}
      conversation={
        detail
          ? {
              pinned: detail.isPinned,
              onPin: () => actions.pin.mutate({ id: detail.id, pinned: !detail.isPinned }),
              onArchive: () =>
                actions.archive.mutate(
                  { id: detail.id, archived: true },
                  { onSuccess: () => navigate(chatRoutes.root) },
                ),
              onDelete: () =>
                actions.remove.mutate(detail.id, { onSuccess: () => navigate(chatRoutes.root) }),
            }
          : null
      }
      onNewChat={() => navigate(chatRoutes.root)}
    />
  );

  return (
    <ChatUiContext.Provider
      value={{
        conversationId: detail?.id ?? null,
        systemId: subject.data?.systemId ?? subjectIds.systemId ?? null,
        systemName: subject.data?.systemName ?? null,
        openPreview: setPreview,
      }}
    >
      {HeaderSlot ? <HeaderSlot>{header}</HeaderSlot> : null}
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
          {!HeaderSlot && <div className="flex h-12 shrink-0 items-center px-3">{header}</div>}

          {notFound ? (
            <div className="grid flex-1 place-items-center p-6">
              <ErrorState title="This chat is not available" error={chat.conversation.error} />
            </div>
          ) : empty ? (
            <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-4 pb-[6vh]">
              <div className="w-full max-w-3xl">
                <div className="mb-4 text-center md:mb-6">
                  <LogoMark
                    className="mx-auto mb-2 size-14 md:size-16 [@media(max-height:640px)]:hidden"
                    title=""
                  />
                  <Greeting text={greeting} />
                  {agent?.description && (
                    <p className="mx-auto max-w-md text-sm text-muted md:text-base [@media(max-height:560px)]:hidden">
                      {agent.description}
                    </p>
                  )}
                </div>
                {noAgentNotice}
                {composerEl}
                <div className="mt-4 flex flex-wrap justify-center gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => {
                        composer.setDraft(s);
                        composerRef.current?.focus();
                      }}
                      className="rounded-full border border-border px-3.5 py-1.5 text-xs text-muted transition-colors hover:border-primary/40 hover:bg-hover hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : chat.conversation.isPending ? (
            <div className="mx-auto w-full max-w-3xl flex-1 space-y-6 px-4 pt-8">
              <Skeleton className="ml-auto h-10 w-2/3 rounded-2xl" />
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : (
            <>
              <ChatBody chat={chat} />
              <div className="mx-auto w-full max-w-3xl px-4">
                {!takeover && noAgentNotice}
                {takeover ?? composerEl}
              </div>
            </>
          )}

          {!notFound && (
            <p className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-3 pt-2.5 text-center text-xs text-muted">
              {CHAT_DISCLAIMER}
            </p>
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
