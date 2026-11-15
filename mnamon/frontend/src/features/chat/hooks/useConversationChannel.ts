/**
 * The open conversation's channel (magenticx `useConversationSources` + the bridge's
 * conversation socket): what the page must learn without having started it.
 *
 * - `run_started`: the server launched a run on its own, a background task's wake-up or the
 *   queued message being sent. The conversation is refetched (the wake-up's notice row and the
 *   new answer join the branch, which follows it via `activeRunId`) and the run is attached, so
 *   the orchestrator's reply streams in live.
 * - `task`: a background task's status changed; written into the task list the agent map reads.
 * - `queue`: the composer queue's state.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { subscribeConversation } from '../lib/transport';
import type { ConversationFrame, QueuedMessage, TaskOut } from '../lib/types';
import { chatKeys } from './keys';
import { seedRun } from './runStore';

const SETTLED = new Set(['success', 'error', 'cancelled']);

/** The task list with one task inserted or replaced. */
export function upsertTask(list: TaskOut[] | undefined, task: TaskOut): TaskOut[] {
  const current = list ?? [];
  const at = current.findIndex((t) => t.task_id === task.task_id);
  if (at < 0) return [...current, task];
  const next = current.slice();
  next[at] = { ...current[at], ...task };
  return next;
}

export function useConversationChannel(
  conversationId: string | null,
  onQueue: (queued: QueuedMessage | null) => void,
) {
  const qc = useQueryClient();
  const queueRef = useRef(onQueue);
  useEffect(() => {
    queueRef.current = onQueue;
  }, [onQueue]);

  useEffect(() => {
    if (!conversationId) return;
    const onFrame = (frame: ConversationFrame) => {
      if (frame.type === 'run_started') {
        seedRun(frame.run);
        void qc.invalidateQueries({ queryKey: chatKeys.detail(conversationId) });
        void qc.invalidateQueries({ queryKey: chatKeys.lists() });
        return;
      }
      if (frame.type === 'task') {
        qc.setQueryData<TaskOut[]>(chatKeys.tasks(conversationId), (list) => upsertTask(list, frame.task));
        // A settle changes the conversation's "has active tasks" flag.
        if (frame.event === 'TASK_STARTED' || SETTLED.has(frame.task.status)) {
          void qc.invalidateQueries({ queryKey: chatKeys.detail(conversationId) });
        }
        return;
      }
      if (frame.type === 'queue') queueRef.current(frame.queued_message);
    };
    return subscribeConversation(conversationId, onFrame);
  }, [conversationId, qc]);
}
