// Mock routes for /v1/audits, registered by src/shared/lib/mocks/handlers/audits.ts.
import { mockError, type MockRoute } from '@/shared/lib/mocks';
import { mockDecide, mockGet, mockList, mockStart } from './mockStore';
import type { ApprovalIn } from './types';

export const auditRoutes: MockRoute[] = [
  {
    method: 'GET',
    path: '/v1/audits',
    // List returns AuditOut (no artifacts / approvals), like the backend.
    handler: ({ query }) =>
      mockList(query.get('systemId')).map(({ artifacts: _a, approvals: _p, ...rest }) => rest),
  },
  {
    method: 'GET',
    path: '/v1/audits/:id',
    handler: ({ params }) => mockGet(params.id) ?? Promise.reject(mockError(404, 'Audit not found')),
  },
  {
    method: 'GET',
    path: '/v1/audits/:id/approvals',
    handler: ({ params }) =>
      mockGet(params.id)?.approvals ?? Promise.reject(mockError(404, 'Audit not found')),
  },
  {
    method: 'POST',
    path: '/v1/audits/:id/approvals',
    handler: ({ params, body }) =>
      mockDecide(params.id, body as ApprovalIn) ?? Promise.reject(mockError(404, 'Audit not found')),
  },
  // Mock audits have no sealed rows: the Findings panel falls back to their finding artifacts.
  { method: 'GET', path: '/v1/audits/:id/findings', handler: () => [] },
  { method: 'GET', path: '/v1/systems/:systemId/findings', handler: () => [] },
  {
    method: 'POST',
    path: '/v1/audits/:id/retry',
    handler: ({ params }) => ({ auditId: params.id, outcome: 'started', status: 'running' }),
  },
  {
    method: 'POST',
    path: '/v1/systems/:systemId/audits',
    handler: ({ params, body }) =>
      mockStart(params.systemId, ((body ?? {}) as { data?: Record<string, unknown> }).data ?? {}),
  },
];
