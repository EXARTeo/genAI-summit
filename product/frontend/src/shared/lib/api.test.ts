import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, buildUrl } from './api';
import { CLIENT_ID_STORAGE_KEY, getClientId } from './client-id';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json', 'X-Request-Id': 'req-1' },
    }),
  );
  vi.stubGlobal('fetch', fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe('api client', () => {
  it('creates and reuses one UUID client id', () => {
    const id = getClientId();
    expect(id).toMatch(UUID);
    expect(localStorage.getItem(CLIENT_ID_STORAGE_KEY)).toBe(id);
    expect(getClientId()).toBe(id);
  });

  it('sends X-Client-Id and prefixes /api', async () => {
    const fetch = mockFetch(200, [{ id: 'SYS-001' }]);
    const out = await api.get<{ id: string }[]>('/v1/systems', {
      query: { prefix: 'docs', none: undefined },
    });
    expect(out[0].id).toBe('SYS-001');
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe('/api/v1/systems?prefix=docs');
    expect((init.headers as Record<string, string>)['X-Client-Id']).toBe(getClientId());
  });

  it('sends JSON bodies with a content type', async () => {
    const fetch = mockFetch(200, { ok: true });
    await api.put('/v1/x', { content: 'a' });
    const [, init] = fetch.mock.calls[0];
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    expect(init.body).toBe('{"content":"a"}');
  });

  it('throws a typed ApiError with the backend detail and request id', async () => {
    mockFetch(404, { detail: 'Conversation not found' });
    const err = await api.get<never>('/v1/conversations/x').catch((e: ApiError) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.isNotFound).toBe(true);
    expect(err.message).toBe('Conversation not found');
    expect(err.requestId).toBe('req-1');
  });

  it('maps network failures to status 0', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const err = await api.get<never>('/v1/systems').catch((e: ApiError) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.isNetwork).toBe(true);
  });

  it('encodes query values', () => {
    expect(buildUrl('v1/a', { q: 'a b', n: 2, f: false })).toBe('/api/v1/a?q=a+b&n=2&f=false');
  });
});
