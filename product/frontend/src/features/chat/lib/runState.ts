/**
 * The pure run-state fold (port of magenticx `features/inference/runState.ts`). A WebSocket
 * frame, a start answer or a cancel/resume answer goes in; the run with its folded timeline
 * comes out.
 *
 * - `events` frames carry only new AG-UI events + run meta: folded incrementally.
 * - `snapshot` / `terminal` frames carry the full state (`run.rawEvents` = the coalesced log):
 *   re-folded from scratch.
 * - `update` is the client-local merge of a cancel/resume REST answer: meta only.
 */
import {
  createTimeline,
  finalizeTimeline,
  foldTimeline,
  reduceTimelineEvents,
  TERMINAL_STATUSES,
  type RunTimeline,
  type TerminalStatus,
} from './timeline';
import type { InferenceRunOut, MessageOut, RawEvent } from './types';

export interface LiveRun extends InferenceRunOut {
  timeline: RunTimeline;
}

export type RunUpdate =
  | { type: 'events'; run: Partial<InferenceRunOut> & { id: string; updatedAt?: string }; events: RawEvent[] }
  | { type: 'snapshot' | 'terminal'; run: InferenceRunOut }
  | { type: 'update'; run: InferenceRunOut };

const ACTIVE = new Set(['queued', 'running', 'cancelling']);

export const isActiveStatus = (status: string | null | undefined) => Boolean(status && ACTIVE.has(status));
export const isActiveRun = (run: { status?: string } | null | undefined) => isActiveStatus(run?.status);

export function foldRunSnapshot(run: InferenceRunOut): LiveRun {
  return {
    ...run,
    timeline: foldTimeline(run.rawEvents, {
      status: String(run.status),
      content: run.content,
      thinking: run.thinking,
    }),
  };
}

export function mergeRunUpdate(existing: LiveRun | null | undefined, update: RunUpdate): LiveRun {
  const base = existing && existing.id === update.run.id ? existing : null;

  if (update.type === 'events') {
    const incoming = update.run;
    const fallback: LiveRun =
      base ??
      ({
        conversationId: '',
        assistantMessageId: incoming.id,
        messagePath: [],
        rawEvents: [],
        startedAt: new Date().toISOString(),
        status: 'running',
        ...incoming,
        updatedAt: incoming.updatedAt ?? new Date().toISOString(),
        timeline: createTimeline(),
      } as LiveRun);
    let timeline = update.events.length
      ? reduceTimelineEvents(fallback.timeline, update.events)
      : fallback.timeline;
    const status = String(incoming.status ?? fallback.status);
    if (TERMINAL_STATUSES.has(status)) timeline = finalizeTimeline(timeline, status as TerminalStatus);
    return {
      ...fallback,
      status,
      pendingInterrupts: incoming.pendingInterrupts ?? fallback.pendingInterrupts,
      errorMessage: incoming.errorMessage ?? fallback.errorMessage ?? null,
      completedAt: incoming.completedAt ?? fallback.completedAt ?? null,
      cancelRequestedAt: incoming.cancelRequestedAt ?? fallback.cancelRequestedAt ?? null,
      updatedAt: incoming.updatedAt ?? fallback.updatedAt,
      timeline,
    };
  }

  if (update.type === 'update' && base) {
    const status = String(update.run.status ?? base.status);
    return {
      ...base,
      status,
      errorMessage: update.run.errorMessage ?? base.errorMessage ?? null,
      completedAt: update.run.completedAt ?? base.completedAt ?? null,
      cancelRequestedAt: update.run.cancelRequestedAt ?? base.cancelRequestedAt ?? null,
      updatedAt: update.run.updatedAt,
      timeline: TERMINAL_STATUSES.has(status)
        ? finalizeTimeline(base.timeline, status as TerminalStatus)
        : base.timeline,
    };
  }

  return foldRunSnapshot(update.run);
}

/** A message the run produced, re-read from its live state (for optimistic rendering). */
export function messageFromRun(run: LiveRun, placeholder: MessageOut): MessageOut {
  return {
    ...placeholder,
    streamingStatus: String(run.status),
    errorMessage: run.errorMessage ?? placeholder.errorMessage,
    error: run.status === 'failed' ? true : placeholder.error,
  };
}
