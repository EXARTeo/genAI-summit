/**
 * Fetch wrapper for the backend. Every call:
 *  - goes to `/api/...` (nginx / the Vite proxy strip `/api` and forward to the backend),
 *  - carries `X-Client-Id` (anonymous browser UUID; the backend scopes data by it),
 *  - throws a typed `ApiError` on non-2xx (status, code, message, details, requestId),
 *  - is answered by the mock router instead when `VITE_USE_MOCKS=true`.
 *
 * Feature `handlers/` call `api.get/post/...`; hooks wrap them in react-query.
 */
import { getClientId } from './client-id';
import { env } from './env';
import { mockFetch } from './mocks';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(opts: { status: number; code: string; message: string; details?: unknown; requestId?: string | null }) {
    super(opts.message);
    this.name = 'ApiError';
    this.status = opts.status;
    this.code = opts.code;
    this.details = opts.details;
    this.requestId = opts.requestId ?? null;
  }

  get isNotFound() {
    return this.status === 404;
  }
  get isRateLimited() {
    return this.status === 429;
  }
  get isNetwork() {
    return this.status === 0;
  }
}

export type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  query?: Query;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** `json` (default), `text` or `blob`. */
  responseType?: 'json' | 'text' | 'blob';
}

export function buildUrl(path: string, query?: Query): string {
  const clean = path.startsWith('/') ? path : `/${path}`;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null) qs.set(k, String(v));
  }
  const s = qs.toString();
  return `${env.apiBase}${clean}${s ? `?${s}` : ''}`;
}

async function toApiError(res: Response): Promise<ApiError> {
  const requestId = res.headers.get('x-request-id');
  let payload: unknown = null;
  try {
    payload = await res.json();
  } catch {
    /* not JSON */
  }
  // Backend errors: {"detail": "..."} or {"error": {"code", "message", ...}} or FastAPI 422 lists.
  const p = (payload ?? {}) as Record<string, unknown>;
  const err = (p.error ?? {}) as Record<string, unknown>;
  const detail = p.detail;
  const message =
    (typeof err.message === 'string' && err.message) ||
    (typeof detail === 'string' && detail) ||
    (Array.isArray(detail) && 'Some fields are invalid') ||
    res.statusText ||
    `HTTP ${res.status}`;
  return new ApiError({
    status: res.status,
    code: (typeof err.code === 'string' && err.code) || `http_${res.status}`,
    message,
    details: Array.isArray(detail) ? detail : (err.details ?? payload),
    requestId,
  });
}

export async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const url = buildUrl(path, opts.query);
  const headers: Record<string, string> = { 'X-Client-Id': getClientId(), ...opts.headers };
  let body: BodyInit | undefined;
  if (opts.body instanceof FormData || opts.body instanceof Blob) {
    body = opts.body;
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }
  const init: RequestInit = { method, headers, body, signal: opts.signal };

  let res: Response;
  try {
    res = env.useMocks ? await mockFetch(url, init) : await fetch(url, init);
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError({ status: 0, code: 'network', message: 'Cannot reach the server' });
  }
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  if (opts.responseType === 'text') return (await res.text()) as T;
  if (opts.responseType === 'blob') return (await res.blob()) as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, opts?: Omit<RequestOptions, 'body'>) => request<T>('GET', path, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('POST', path, { ...opts, body }),
  put: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('PUT', path, { ...opts, body }),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('PATCH', path, { ...opts, body }),
  delete: <T>(path: string, opts?: RequestOptions) => request<T>('DELETE', path, opts),
};

/** WebSocket URL for a backend socket path (same origin, through the proxy). */
export function wsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}${buildUrl(path)}`;
}
