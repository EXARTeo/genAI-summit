// Mock of POST /v1/systems (the Register a system wizard, plan 02).
import type { SystemCard } from '@/features/systems/lib/types';
import { mockSystems } from '../fixtures/systems';
import { MockResponse, mockError, type MockRoute } from '../types';

const SYSTEM_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

export const routes: MockRoute[] = [
  {
    method: 'POST',
    path: '/v1/systems',
    handler: ({ body }) => {
      const b = (body ?? {}) as { id?: string; name?: string; status?: string; data?: SystemCard };
      if (!b.id || !SYSTEM_ID.test(b.id)) return mockError(422, 'id: letters, digits, ".", "_", "-"');
      if (!b.name?.trim()) return mockError(422, 'name: required');
      if (mockSystems.get(b.id)) return mockError(409, `System ${b.id} already exists`);
      return new MockResponse(
        201,
        mockSystems.create({ id: b.id, name: b.name, status: b.status ?? 'active', data: b.data ?? {} }),
      );
    },
  },
];
