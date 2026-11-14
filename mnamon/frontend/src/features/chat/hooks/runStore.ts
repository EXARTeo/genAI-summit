/**
 * Live runs, app-wide (port of magenticx `features/inference/useInferenceRuns.ts`). One entry per
 * run id, folded from the run socket by `mergeRunUpdate`. Kept in a store rather than a page so a
 * run keeps streaming while the user looks at another conversation, and the sidebar can show it.
 */
import { create } from 'zustand';
import type { QueryClient } from '@tanstack/react-query';
import { queryClient as defaultClient } from '@/shared/lib/query-client';
import { mergeRunUpdate, isActiveRun, type LiveRun, type RunUpdate } from '../lib/runState';
import { listRuns } from '../handlers/chat';
import { subscribeRun, type Unsubscribe } from '../lib/transport';
import type { ConversationDetail, InferenceRunOut, MessageOut, RunFrame } from '../lib/types';
import { chatKeys } from './keys';

interface RunStore {
  runs: Record<string, LiveRun>;
  /** Approvals the user already answered, until the run's resolution event arrives. */
  decided: Record<string, true>;
  apply: (update: RunUpdate) => void;
  markDecided: (interruptId: string) => void;
}

export const useRunStore = create<RunStore>((set) => ({
  runs: {},
  decided: {},
  apply: (update) =>
    set((s) => ({ runs: { ...s.runs, [update.run.id]: mergeRunUpdate(s.runs[update.run.id], update) } })),
  markDecided: (interruptId) => set((s) => ({ decided: { ...s.decided, [interruptId]: true } })),
}));

const sockets = new Map<string, Unsubscribe>();
let queryClient: QueryClient = defaultClient;

/** The react-query client the run frames write into (the provider's, set by useChat). */
export function bindQueryClient(client: QueryClient) {
  queryClient = client;
}

/** Write a message the server sent into the cached conversation (insert or replace). */
export function patchCachedMessage(
  conversationId: string,
  message: MessageOut,
  extra: Partial<ConversationDetail> = {},
) {
  queryClient.setQueryData<ConversationDetail>(chatKeys.detail(conversationId), (prev) => {
    if (!prev) return prev;
    const exists = prev.messages.some((m) => m.id === message.id);
    const messages = exists
      ? prev.messages.map((m) => (m.id === message.id ? message : m))
      : [...prev.messages, message];
    return { ...prev, ...extra, messages };
  });
}

function onFrame(runId: string, frame: RunFrame) {
  const { apply } = useRunStore.getState();
  if (frame.type === 'event') {
    const payload = frame.payload;
    if (payload.type === 'events') apply({ type: 'events', run: payload.run, events: payload.events });
    else apply({ type: payload.type, run: payload.run });
    return;
  }
  const payload = frame.payload;
  if (!payload) {
    detachRun(runId);
    return;
  }
  apply({ type: frame.type, run: payload.run });
  if (frame.type === 'terminal' || !isActiveRun(payload.run)) {
    const conversationId = payload.run.conversationId;
    if (payload.message) {
      patchCachedMessage(conversationId, payload.message, payload.summary ? { ...payload.summary } : {});
    }
    void queryClient.invalidateQueries({ queryKey: chatKeys.lists() });
    if (frame.type === 'terminal') detachRun(runId);
  }
}

/** Open the run socket once (idempotent). */
export function attachRun(runId: string) {
  if (sockets.has(runId)) return;
  const off = subscribeRun(runId, {
    onFrame: (frame) => onFrame(runId, frame),
    onGiveUp: () => {
      detachRun(runId);
      pollRun(runId);
    },
  });
  sockets.set(runId, off);
}

const POLL_MS = 3000;
const POLL_LIMIT = 200;

/**
 * The socket gave up (blocked origin, proxy without WebSocket upgrade, lost network): read the
 * run's status over REST until it settles, so the answer never stays "Starting" forever.
 */
function pollRun(runId: string, attempt = 0) {
  void listRuns()
    .then((runs) => {
      const run = runs.find((r) => r.id === runId);
      // A listed run carries its event log: re-fold it, so a socket-less run still shows progress.
      if (run) useRunStore.getState().apply({ type: 'snapshot', run });
      if (run && isActiveRun(run) && attempt < POLL_LIMIT) {
        setTimeout(() => pollRun(runId, attempt + 1), POLL_MS);
        return;
      }
      if (!run) {
        const live = useRunStore.getState().runs[runId];
        if (live && isActiveRun(live)) {
          useRunStore
            .getState()
            .apply({ type: 'update', run: { ...live, status: 'failed' } as InferenceRunOut });
        }
      }
      void queryClient.invalidateQueries({ queryKey: chatKeys.all });
    })
    .catch(() => {
      if (attempt < POLL_LIMIT) setTimeout(() => pollRun(runId, attempt + 1), POLL_MS);
    });
}

export function detachRun(runId: string) {
  sockets.get(runId)?.();
  sockets.delete(runId);
}

/** Seed a run from a REST answer (start / cancel / resume) and make sure it is attached. */
export function seedRun(run: InferenceRunOut, kind: 'snapshot' | 'update' = 'snapshot') {
  const existing = useRunStore.getState().runs[run.id];
  useRunStore
    .getState()
    .apply(existing && kind === 'snapshot' ? { type: 'update', run } : { type: kind, run });
  if (isActiveRun(run)) attachRun(run.id);
}
