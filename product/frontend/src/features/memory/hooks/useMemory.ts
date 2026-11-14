import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { memoryApi } from '../handlers/memory';
import type { MemoryAction } from '../lib/memory';

export const memoryKeys = { ledger: ['memory', 'ledger'] as const };

export function useMemoryLedger() {
  return useQuery({ queryKey: memoryKeys.ledger, queryFn: memoryApi.ledger });
}

export function useMemoryAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; action: MemoryAction; reason: string }) => memoryApi.act(v.id, v.action, v.reason),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: memoryKeys.ledger });
    },
  });
}
