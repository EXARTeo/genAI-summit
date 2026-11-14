// Memory ledger calls. The backend stores memory as YAML files under /v1/memory/{org,systems/<id>,proposals}
// (product/backend/router/memory.py); `/v1/memory/ledger` is the parsed, indexed view this UI needs
// (served by the mock router today; backend endpoint pending).
import { api } from '@/shared/lib/api';
import type { MemoryAction } from '../lib/memory';
import type { MemoryEntry } from '../lib/types';

export const memoryApi = {
  ledger: () => api.get<MemoryEntry[]>('/v1/memory/ledger'),
  entry: (id: string) => api.get<MemoryEntry>(`/v1/memory/ledger/${encodeURIComponent(id)}`),
  act: (id: string, action: MemoryAction, reason: string) =>
    api.post<MemoryEntry>(`/v1/memory/ledger/${encodeURIComponent(id)}/${action}`, { reason }),
};
