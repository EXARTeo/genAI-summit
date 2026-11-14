import { MockResponse, type MockRoute } from './types';

const modules = import.meta.glob<{ routes?: MockRoute[] }>('./handlers/*.ts', { eager: true });

interface CompiledRoute extends MockRoute {
  regex: RegExp;
  keys: string[];
}

function compile(route: MockRoute): CompiledRoute {
  const keys: string[] = [];
  const pattern = route.path
    .split('/')
    .map((seg) => {
      if (seg.startsWith(':')) {
        keys.push(seg.slice(1));
        return '([^/]+)';
      }
      if (seg.startsWith('*')) {
        keys.push(seg.slice(1));
        return '(.+)';
      }
      return seg.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    })
    .join('/');
  return { ...route, keys, regex: new RegExp(`^${pattern}/?$`) };
}

// Longer (more specific) paths first, so `/files/*path/versions` beats `/files/*path`.
const ROUTES: CompiledRoute[] = Object.values(modules)
  .flatMap((m) => m.routes ?? [])
  .map(compile)
  .sort((a, b) => b.path.split('/').length - a.path.split('/').length);

function latency(): Promise<void> {
  const ms = import.meta.env.MODE === 'test' ? 0 : 180 + Math.random() * 320;
  return new Promise((r) => setTimeout(r, ms));
}

export async function handleMockRequest(url: string, init: RequestInit): Promise<Response> {
  const parsed = new URL(url, 'http://mock.local');
  const path = parsed.pathname.replace(/^\/api/, '');
  const method = (init.method ?? 'GET').toUpperCase();
  await latency();

  for (const route of ROUTES) {
    if (route.method !== method) continue;
    const m = route.regex.exec(path);
    if (!m) continue;
    const params = Object.fromEntries(route.keys.map((k, i) => [k, decodeURIComponent(m[i + 1])]));
    let body: unknown;
    if (init.body instanceof FormData) body = init.body;
    else if (typeof init.body === 'string') body = JSON.parse(init.body);
    try {
      const out = await route.handler({
        params,
        query: parsed.searchParams,
        body,
        headers: new Headers(init.headers),
      });
      if (out instanceof MockResponse) return toResponse(out);
      if (out === undefined) return new Response(null, { status: 204 });
      return toResponse(new MockResponse(200, out));
    } catch (e) {
      if (e instanceof MockResponse) return toResponse(e);
      return toResponse(new MockResponse(500, { detail: String(e) }));
    }
  }
  return toResponse(new MockResponse(404, { detail: `No mock for ${method} ${path}` }));
}

function toResponse(r: MockResponse): Response {
  const isJson = r.contentType === 'application/json';
  return new Response(isJson ? JSON.stringify(r.body) : (r.body as BodyInit), {
    status: r.status,
    headers: { 'Content-Type': r.contentType, 'X-Request-Id': `mock-${Date.now().toString(36)}` },
  });
}
