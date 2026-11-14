/**
 * The chat controller (port of magenticx `app/useChatWorkspace.tsx` + `handlers/messages.tsx` +
 * `features/inference/useInferenceRuns.ts`, for one conversation): the visible branch, the live
 * run, and every action the page offers (send, edit, retry, stop, approve / reject, answer,
 * rate, switch branch).
 */
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError } from '@/shared/lib/api';
import { toast } from '@/shared/ui';
import { cancelRun, rateMessage, resumeRun, startRun } from '../handlers/chat';
import { toAttachmentIn, type PendingAttachment } from '../lib/attachments';
import { pathTo, selectionFor, selectSibling, visiblePath, type BranchSelection } from '../lib/branches';
import type { AskUserAnswer } from '../lib/hitl';
import { chatRoutes } from '../lib/routes';
import { foldRunSnapshot, isActiveRun, isActiveStatus, type LiveRun } from '../lib/runState';
import { pendingInterrupts, type Approval } from '../lib/timeline';
import type {
  AgentManifest,
  ConversationDetail,
  InferenceStartPayload,
  InferenceStartResponse,
  MessageOut,
  QueuedStartResponse,
  ResumeDecision,
} from '../lib/types';
import { chatKeys } from './keys';
import { attachRun, bindQueryClient, patchCachedMessage, seedRun, useRunStore } from './runStore';
import { useConversation } from './useConversations';

export interface ChatSubject {
  systemId?: string | null;
  auditId?: string | null;
}

export interface SendInput {
  text: string;
  attachments: PendingAttachment[];
}

const foldCache = new WeakMap<MessageOut, LiveRun>();

const isQueued = (r: InferenceStartResponse | QueuedStartResponse): r is QueuedStartResponse =>
  (r as QueuedStartResponse).queued === true;

function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : 'Something went wrong';
}

export function useChat(
  conversationId: string | null,
  opts: { agent: AgentManifest | null; subject: ChatSubject },
) {
  const qc = useQueryClient();
  bindQueryClient(qc);
  const navigate = useNavigate();
  const conversation = useConversation(conversationId);
  const detail = conversation.data ?? null;
  const [selection, setSelection] = useState<BranchSelection>({});
  const [sending, setSending] = useState(false);
  const [queued, setQueued] = useState<string | null>(null);
  const runs = useRunStore((s) => s.runs);
  const decided = useRunStore((s) => s.decided);

  // A new conversation starts on its newest branch (or the one a task is working on).
  useEffect(() => {
    setSelection({});
    setQueued(null);
  }, [conversationId]);
  useEffect(() => {
    if (!detail) return;
    const focus = detail.activeRunId ?? detail.activeTaskMessageId;
    if (focus && detail.messages.some((m) => m.id === focus))
      setSelection((s) => selectionFor(detail.messages, focus, s));
    // Attach to whatever is still running (a reload, or a run started elsewhere).
    for (const m of detail.messages) {
      if (m.sender === 'ai' && isActiveStatus(m.streamingStatus)) attachRun(m.id);
    }
    if (detail.activeRunId) attachRun(detail.activeRunId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail?.id, detail?.activeRunId]);

  const messages = useMemo(() => detail?.messages ?? [], [detail?.messages]);
  const path = useMemo(() => visiblePath(messages, selection), [messages, selection]);

  /** The live run of this conversation, if any (shown on its AI message). */
  const activeRun: LiveRun | null = useMemo(() => {
    const live = Object.values(runs).filter((r) => r.conversationId === conversationId && isActiveRun(r));
    return live.sort((a, b) => b.startedAt.localeCompare(a.startedAt))[0] ?? null;
  }, [runs, conversationId]);

  const runFor = useCallback((messageId: string): LiveRun | null => runs[messageId] ?? null, [runs]);

  /** Pending approvals of the active run, minus ones the user already answered. */
  const pending: Approval[] = useMemo(
    () => (activeRun ? pendingInterrupts(activeRun.timeline).filter((i) => !decided[i.id]) : []),
    [activeRun, decided],
  );

  const applyStart = useCallback(
    (res: InferenceStartResponse, isNew: boolean) => {
      const { summary, run, message, userMessage } = res;
      if (isNew) {
        const created: ConversationDetail = {
          ...summary,
          messages: [userMessage, message].filter(Boolean) as MessageOut[],
        };
        qc.setQueryData(chatKeys.detail(summary.id), created);
      } else {
        if (userMessage) patchCachedMessage(summary.id, userMessage, { ...summary });
        patchCachedMessage(summary.id, message, { ...summary });
      }
      useRunStore.getState().apply({ type: 'snapshot', run });
      seedRun(run);
      setSelection((s) => {
        const all = qc.getQueryData<ConversationDetail>(chatKeys.detail(summary.id))?.messages ?? [];
        return selectionFor(all, message.id, isNew ? {} : s);
      });
      void qc.invalidateQueries({ queryKey: chatKeys.lists() });
      if (isNew) navigate(chatRoutes.conversation(summary.id));
    },
    [qc, navigate],
  );

  const start = useCallback(
    async (payload: InferenceStartPayload) => {
      setSending(true);
      try {
        const res = await startRun(payload);
        if (isQueued(res)) {
          setQueued(res.queued_message.content ?? '');
          toast.info('Queued: sent when the current answer finishes');
          return true;
        }
        applyStart(res, payload.mode === 'new');
        return true;
      } catch (e) {
        toast.error(errorText(e));
        return false;
      } finally {
        setSending(false);
      }
    },
    [applyStart],
  );

  const agentFields = opts.agent ? { agentSlug: opts.agent.slug, agentName: opts.agent.name } : {};

  const send = useCallback(
    async ({ text, attachments }: SendInput) => {
      const message = {
        sender: 'user' as const,
        content: text.trim() || null,
        attachments: attachments.map(toAttachmentIn),
      };
      if (!detail) {
        return start({
          mode: 'new',
          ...agentFields,
          agentSlug: opts.agent?.slug ?? 'assistant',
          systemId: opts.subject.systemId ?? undefined,
          auditId: opts.subject.auditId ?? undefined,
          message,
        });
      }
      const last = path[path.length - 1];
      return start({
        mode: 'send',
        conversationId: detail.id,
        parentMessageId: last?.id ?? null,
        ...(opts.agent && opts.agent.slug !== detail.agentSlug ? agentFields : {}),
        message: { ...message, parentMessageId: last?.id ?? null },
        queue_if_busy: Boolean(activeRun),
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [detail, path, start, opts.agent, opts.subject.systemId, opts.subject.auditId, activeRun],
  );

  const edit = useCallback(
    (messageId: string, text: string) =>
      detail
        ? start({
            mode: 'edit',
            conversationId: detail.id,
            targetMessageId: messageId,
            message: { sender: 'user', content: text },
          })
        : Promise.resolve(false),
    [detail, start],
  );

  const retry = useCallback(
    (aiMessageId: string) => {
      if (!detail) return Promise.resolve(false);
      const ai = messages.find((m) => m.id === aiMessageId);
      return start({
        mode: 'retry',
        conversationId: detail.id,
        targetMessageId: aiMessageId,
        messagePath: ai?.parentMessageId ? pathTo(messages, ai.parentMessageId) : undefined,
      });
    },
    [detail, messages, start],
  );

  const stop = useCallback(async () => {
    if (!activeRun) return;
    try {
      const run = await cancelRun(activeRun.id);
      useRunStore.getState().apply({ type: 'update', run });
    } catch (e) {
      toast.error(errorText(e));
    }
  }, [activeRun]);

  const decide = useCallback(
    async (approval: Approval, decisions: ResumeDecision[], value?: unknown) => {
      if (!activeRun) return;
      const overall =
        decisions.length === 1
          ? decisions[0].decision
          : decisions.some((d) => d.decision === 'approve')
            ? 'approve'
            : 'reject';
      try {
        useRunStore.getState().markDecided(approval.id);
        await resumeRun(activeRun.id, {
          interruptId: approval.id,
          decision: overall,
          reason: decisions.length === 1 ? (decisions[0].reason ?? null) : null,
          decisions: decisions.length > 1 ? decisions : undefined,
          value,
        });
      } catch (e) {
        toast.error(errorText(e));
      }
    },
    [activeRun],
  );

  const answer = useCallback(
    (approval: Approval, answers: AskUserAnswer[] | null) =>
      decide(approval, [{ decision: answers ? 'approve' : 'reject' }], answers ? { answers } : undefined),
    [decide],
  );

  const rate = useCallback(
    async (message: MessageOut, liked: boolean) => {
      if (!detail) return;
      const next = message.liked === liked ? null : liked;
      patchCachedMessage(detail.id, { ...message, liked: next });
      try {
        await rateMessage(detail.id, message.id, liked);
      } catch (e) {
        patchCachedMessage(detail.id, message);
        toast.error(errorText(e));
      }
    },
    [detail],
  );

  const switchBranch = useCallback(
    (message: MessageOut, index: number) => setSelection((s) => selectSibling(messages, message, index, s)),
    [messages],
  );

  /** A run as the message list renders it: the live fold, or the stored message folded once. */
  const runView = useCallback(
    (message: MessageOut): LiveRun | null => {
      const live = runFor(message.id);
      if (live) return live;
      if (message.sender !== 'ai') return null;
      const cached = foldCache.get(message);
      if (cached) return cached;
      const folded = foldRunSnapshot({
        id: message.id,
        conversationId: detail?.id ?? '',
        assistantMessageId: message.id,
        status: message.streamingStatus ?? (message.error ? 'failed' : 'completed'),
        messagePath: [],
        content: message.content,
        thinking: message.thinking,
        rawEvents: message.rawEvents,
        errorMessage: message.errorMessage,
        startedAt: message.created_at,
        updatedAt: message.updated_at,
      });
      foldCache.set(message, folded);
      return folded;
    },
    [runFor, detail?.id],
  );

  return {
    conversation,
    detail,
    messages,
    path,
    activeRun,
    pending,
    sending,
    queued,
    runView,
    send,
    edit,
    retry,
    stop,
    decide,
    answer,
    rate,
    switchBranch,
  };
}

export type ChatController = ReturnType<typeof useChat>;
