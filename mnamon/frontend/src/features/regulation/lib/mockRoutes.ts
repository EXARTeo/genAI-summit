// Mock routes for /v1/regulation, registered by src/shared/lib/mocks/handlers/regulation.ts.
import { mockError, type MockRoute } from '@/shared/lib/mocks';
import {
  buildMockChanges,
  buildMockSources,
  mockDocDiff,
  mockDocText,
  mockProvisions,
  mockReleases,
} from './mocks';
import type { JudgeDecision, RegChange } from './types';

let changes: RegChange[] | null = null;
const db = () => (changes ??= buildMockChanges());

function find(id: string): RegChange {
  const c = db().find((x) => x.id === id);
  if (!c) throw mockError(404, 'Change not found');
  return c;
}

export const regulationRoutes: MockRoute[] = [
  {
    method: 'POST',
    path: '/v1/regulation/check-now',
    handler: () => ({ check_id: `chk-${Date.now().toString(36)}`, status: 'queued' }),
  },
  { method: 'GET', path: '/v1/regulation/sources', handler: () => buildMockSources() },
  {
    method: 'GET',
    path: '/v1/regulation/documents/:docId/text',
    handler: ({ params, query }) =>
      mockDocText(params.docId, query.get('version') ? Number(query.get('version')) : undefined),
  },
  {
    method: 'GET',
    path: '/v1/regulation/documents/:docId/diff',
    handler: ({ params }) => mockDocDiff(params.docId),
  },
  { method: 'GET', path: '/v1/regulation/changes', handler: () => db() },
  { method: 'GET', path: '/v1/regulation/releases', handler: () => mockReleases() },
  {
    method: 'GET',
    path: '/v1/regulation/provisions',
    handler: ({ query }) => mockProvisions(query.get('kb_version')),
  },
  {
    method: 'GET',
    path: '/v1/regulation/provisions/:id',
    handler: ({ params, query }) => {
      const p = mockProvisions(query.get('kb_version')).items.find((x) => x.id === params.id);
      if (!p) throw mockError(404, 'Not found in reg-memory.');
      return p;
    },
  },
  {
    method: 'POST',
    path: '/v1/regulation/changes/:id/decision',
    handler: ({ params, body }) => {
      const c = find(params.id);
      c.status = (body as { status: RegChange['status'] }).status;
      return c;
    },
  },
  {
    method: 'POST',
    path: '/v1/regulation/changes/:id/systems/:systemId',
    handler: ({ params, body }) => {
      const c = find(params.id);
      c.affected = c.affected.map((a) =>
        a.systemId === params.systemId
          ? { ...a, humanDecision: (body as { decision: JudgeDecision }).decision }
          : a,
      );
      return c;
    },
  },
];
