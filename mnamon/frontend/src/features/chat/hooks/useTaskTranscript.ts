/**
 * A background task's event log, live, for its agent-map detail: the task socket's `snapshot`
 * (with the stored events once the task has settled), then each `event` frame as it streams.
 * Folded by `lib/taskTranscript.ts` into the task's whole conversation.
 */
import { useEffect, useMemo, useState } from 'react';
import { foldTaskEvents } from '../lib/taskTranscript';
import type { RunTimeline } from '../lib/timeline';
import { subscribeTask } from '../lib/transport';
import type { RawEvent, TaskSocketFrame } from '../lib/types';

export interface TaskTranscriptState {
  timeline: RunTimeline | null;
  /** The task's status as the socket last reported it. */
  status: string | null;
  /** True once the first frame arrived (or the socket gave up). */
  loaded: boolean;
}

interface Log {
  taskId: string | null;
  events: RawEvent[];
  status: string | null;
  loaded: boolean;
}

export function useTaskTranscript(taskId: string | null): TaskTranscriptState {
  const [log, setLog] = useState<Log>({ taskId: null, events: [], status: null, loaded: false });

  useEffect(() => {
    if (!taskId) return;
    setLog({ taskId, events: [], status: null, loaded: false });
    const onFrame = (frame: TaskSocketFrame) => {
      setLog((current) => {
        if (current.taskId !== taskId) return current;
        if (frame.type === 'snapshot') {
          // A reconnect sends a snapshot without events: keep what streamed so far.
          return {
            taskId,
            events: frame.events ?? current.events,
            status: frame.task.status,
            loaded: true,
          };
        }
        if (frame.type === 'event')
          return { ...current, events: [...current.events, frame.event], loaded: true };
        return { ...current, status: frame.status, loaded: true };
      });
    };
    return subscribeTask(taskId, onFrame, () => setLog((current) => ({ ...current, loaded: true })));
  }, [taskId]);

  const timeline = useMemo(
    () => (log.taskId === taskId && log.events.length ? foldTaskEvents(log.events, log.status) : null),
    [log, taskId],
  );
  return {
    timeline,
    status: log.taskId === taskId ? log.status : null,
    loaded: log.taskId === taskId && log.loaded,
  };
}
