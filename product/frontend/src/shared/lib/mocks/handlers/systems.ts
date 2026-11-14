import { mockSystems, ruleProposals, writeFile } from '../fixtures/systems';
import { MockResponse, mockError, type MockRoute } from '../types';

const notFound = () => mockError(404, 'System not found');

async function bodyText(body: unknown): Promise<{ text: string; reason: string | null }> {
  if (body instanceof FormData) {
    const f = body.get('file');
    return {
      text: f instanceof Blob ? await f.text() : String(f ?? ''),
      reason: (body.get('reason') as string) ?? null,
    };
  }
  const b = (body ?? {}) as { content?: string; reason?: string };
  return { text: b.content ?? '', reason: b.reason ?? null };
}

export const routes: MockRoute[] = [
  { method: 'GET', path: '/v1/systems', handler: () => mockSystems.list() },
  {
    method: 'GET',
    path: '/v1/systems/:systemId',
    handler: ({ params }) => mockSystems.get(params.systemId) ?? notFound(),
  },
  {
    method: 'GET',
    path: '/v1/systems/:systemId/files',
    handler: ({ params, query }) =>
      mockSystems.get(params.systemId) ? mockSystems.tree(params.systemId, query.get('prefix')) : notFound(),
  },
  {
    method: 'GET',
    path: '/v1/systems/:systemId/events',
    handler: ({ params }) => mockSystems.events(params.systemId),
  },
  {
    method: 'GET',
    path: '/v1/systems/:systemId/files/*path/versions',
    handler: ({ params }) => {
      const v = mockSystems.versions(params.systemId, params.path);
      return v.length ? v : mockError(404, 'File not found');
    },
  },
  {
    method: 'GET',
    path: '/v1/systems/:systemId/files/*path',
    handler: ({ params, query }) => {
      const version = query.get('version');
      const f = mockSystems.read(params.systemId, params.path, version ? Number(version) : undefined);
      if (!f) return mockError(404, 'File not found');
      return query.get('format') === 'json' ? f : new MockResponse(200, f.text, f.contentType);
    },
  },
  {
    method: 'PUT',
    path: '/v1/systems/:systemId/files/*path',
    handler: async ({ params, body }) => {
      if (!mockSystems.get(params.systemId)) return notFound();
      const { text, reason } = await bodyText(body);
      return writeFile(params.systemId, params.path, text, 'user:demo', reason);
    },
  },
  {
    method: 'PUT',
    path: '/v1/memory/proposals/files/rules/*path',
    handler: async ({ params, body }) => {
      const { text } = await bodyText(body);
      const at = new Date().toISOString();
      ruleProposals.push({ path: `rules/${params.path}`, text, at });
      return {
        file: {
          namespace: 'memory:proposals',
          path: `rules/${params.path}`,
          version: 1,
          contentType: 'application/yaml',
          size: text.length,
          sha256: '0'.repeat(64),
          createdBy: 'user:demo',
          isCurrent: true,
          data: {},
          createdAt: at,
        },
        changed: true,
      };
    },
  },
];
