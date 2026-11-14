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
import type { RunFrame } from './types';

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

  let socket: WebSocket | null = null;
  let since: string | null = null;
  let done = false;
  let retries = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const connect = () => {
    socket = new WebSocket(socketUrl(chatApi.runSocket(runId)));
    socket.onopen = () => {
      retries = 0;
      socket?.send(JSON.stringify({ type: 'subscribe', since }));
    };
    socket.onmessage = (msg) => {
      let frame: RunFrame;
      try {
        frame = JSON.parse(String(msg.data)) as RunFrame;
      } catch {
        return;
      }
      if (frame.type === 'event' && frame.seq) since = frame.seq;
      if (frame.type === 'terminal') done = true;
      handlers.onFrame(frame);
    };
    socket.onclose = (e) => {
      if (done) return;
      if (e.code === 4404 || e.code === 4403) {
        done = true;
        handlers.onGiveUp?.('Run not found');
        return;
      }
      if (retries >= MAX_RETRIES) {
        done = true;
        handlers.onGiveUp?.('Lost the connection to the run');
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
