// Mock routes for the memory ledger, registered by src/shared/lib/mocks/handlers/memory.ts.
import { mockError, type MockRoute } from '@/shared/lib/mocks';
import { nextMemoryId } from './memory';
import { buildMockMemory } from './mocks';
import type { MemoryEntry, MemoryEvent } from './types';

let ledger: MemoryEntry[] | null = null;
const db = () => (ledger ??= buildMockMemory());

function find(id: string): MemoryEntry {
  const e = db().find((x) => x.id === id);
  if (!e) throw mockError(404, 'Memory entry not found');
  return e;
}

function log(e: MemoryEntry, action: MemoryEvent['action'], reason: string, actor = 'engineer:you'): void {
  e.history = [...e.history, { action, actor, at: new Date().toISOString(), reason: reason || undefined }];
}

export const memoryRoutes: MockRoute[] = [
  { method: 'GET', path: '/v1/memory/ledger', handler: () => db() },
  { method: 'GET', path: '/v1/memory/ledger/:id', handler: ({ params }) => find(params.id) },
  {
    method: 'POST',
    path: '/v1/memory/ledger/:id/:action',
    handler: ({ params, body }) => {
      const e = find(params.id);
      const reason = ((body as { reason?: string } | undefined)?.reason ?? '').trim();
      switch (params.action) {
        case 'approve':
        case 'reactivate':
          e.status = 'active';
          e.approvedBy = 'engineer:you';
          log(e, 'approve', reason);
          return e;
        case 'retire':
          e.status = 'retired';
          log(e, 'retire', reason);
          return e;
        case 'promote': {
          const org: MemoryEntry = {
            ...e,
            id: nextMemoryId(db()),
            scope: 'org',
            kind: 'precedent',
            status: 'proposed',
            approvedBy: null,
            promotedFrom: e.id,
            usageCount: 0,
            version: 1,
            createdAt: new Date().toISOString(),
            history: [{ action: 'create', actor: 'engineer:you', at: new Date().toISOString(), reason: `Promoted from ${e.id}; waiting for the AI Officer` }],
          };
          log(e, 'promote', reason || `→ ${org.id}`);
          ledger = [org, ...db()];
          return org;
        }
        default:
          throw mockError(400, `Unknown action ${params.action}`);
      }
    },
  },
];
