/**
 * The run socket (port of magenticx `shared/lib/api/{inference-socket,reconnecting-socket}.ts`).
 *
 * `WS /v1/inference/runs/{id}/ws?client_id=…`: the first client frame is
 * `{"type": "subscribe", "since": <last seq> | null}`; the server answers `snapshot`, then
 * `event` frames (`seq` + one `events` payload), then `terminal` before it closes. On an
 * unexpected close we reconnect with the last `seq` so nothing is lost or repeated.
 *
 * In mock mode the frames come from the in-browser run simulator instead.
 */
import { getClientId } from '@/shared/lib/client-id';
import { env } from '@/shared/lib/env';
import { buildUrl } from '@/shared/lib/api';
import { chatApi } from './routes';
import type { ConversationFrame, RunFrame, TaskSocketFrame } from './types';

export type Unsubscribe = () => void;

export interface RunSocketHandlers {
  onFrame: (frame: RunFrame) => void;
  /** The socket gave up (4404, or too many failed reconnects). */
  onGiveUp?: (reason: string) => void;
}

const MAX_RETRIES = 6;

function socketUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}${buildUrl(path, { client_id: getClientId() })}`;
}

export function subscribeRun(runId: string, handlers: RunSocketHandlers): Unsubscribe {
  if (env.useMocks) {
    let off: Unsubscribe | null = null;
    let closed = false;
    void import('./mockRuns').then((m) => {
      if (!closed) off = m.subscribeMockRun(runId, handlers.onFrame);
    });
    return () => {
      closed = true;
      off?.();
    };
  }

  return subscribeSocket<RunFrame>(chatApi.runSocket(runId), {
    onFrame: handlers.onFrame,
    onGiveUp: handlers.onGiveUp,
    isTerminal: (frame) => frame.type === 'terminal',
    notFound: 'Run not found',
    lost: 'Lost the connection to the run',
  });
}

interface SocketOptions<F> {
  onFrame: (frame: F) => void;
  onGiveUp?: (reason: string) => void;
  /** The server's last frame: the socket closes after it and is not reopened. */
  isTerminal?: (frame: F) => boolean;
  notFound: string;
  lost: string;
}

/**
 * One reconnecting subscription (`subscribe` with the last `seq` as `since`, so a reconnect loses
 * and repeats nothing). Shared by the run, conversation and task sockets.
 */
function subscribeSocket<F extends { type: string; seq?: string }>(
  path: string,
  options: SocketOptions<F>,
): Unsubscribe {
  let socket: WebSocket | null = null;
  let since: string | null = null;
  let done = false;
  let retries = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const connect = () => {
    socket = new WebSocket(socketUrl(path));
    socket.onopen = () => {
      retries = 0;
      socket?.send(JSON.stringify({ type: 'subscribe', since }));
    };
    socket.onmessage = (msg) => {
      let frame: F;
      try {
        frame = JSON.parse(String(msg.data)) as F;
      } catch {
        return;
      }
      if (typeof frame.seq === 'string' && frame.seq) since = frame.seq;
      if (options.isTerminal?.(frame)) done = true;
      options.onFrame(frame);
    };
    socket.onclose = (e) => {
      if (done) return;
      if (e.code === 4404 || e.code === 4403) {
        done = true;
        options.onGiveUp?.(options.notFound);
        return;
      }
      if (retries >= MAX_RETRIES) {
        done = true;
        options.onGiveUp?.(options.lost);
        return;
      }
      retries += 1;
      timer = setTimeout(connect, Math.min(8000, 400 * 2 ** retries));
    };
  };
  connect();

  return () => {
    done = true;
    clearTimeout(timer);
    socket?.close();
  };
}

/**
 * The conversation channel (`WS /v1/inference/conversations/{id}/ws`): background-task status
 * changes, runs the server started on its own (a task wake-up, the queued message being sent) and
 * the composer queue. Nothing in mock mode.
 */
export function subscribeConversation(
  conversationId: string,
  onFrame: (frame: ConversationFrame) => void,
): Unsubscribe {
  if (env.useMocks) return () => undefined;
  return subscribeSocket<ConversationFrame>(chatApi.conversationSocket(conversationId), {
    onFrame,
    notFound: 'Conversation not found',
    lost: 'Lost the connection to the conversation',
  });
}

/**
 * One background task's events (`WS /v1/tasks/{id}/ws`): a `snapshot` (with the stored `events`
 * once it has settled), live `event` frames, then `terminal`. Nothing in mock mode.
 */
export function subscribeTask(
  taskId: string,
  onFrame: (frame: TaskSocketFrame) => void,
  onGiveUp?: (reason: string) => void,
): Unsubscribe {
  if (env.useMocks) return () => undefined;
  return subscribeSocket<TaskSocketFrame>(chatApi.taskSocket(taskId), {
    onFrame,
    onGiveUp,
    isTerminal: (frame) => frame.type === 'terminal',
    notFound: 'Task not found',
    lost: 'Lost the connection to the task',
  });
}
