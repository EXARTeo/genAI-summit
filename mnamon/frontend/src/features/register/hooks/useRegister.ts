import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { closeRegisterItem, fetchRegister, reopenRegisterItem } from '../handlers/register';

export const registerKeys = {
  all: ['register'] as const,
  system: (systemId: string) => ['register', systemId] as const,
};

/** The system's findings register (state per obligation across audits). */
export function useRegister(systemId: string | undefined) {
  return useQuery({
    queryKey: registerKeys.system(systemId ?? ''),
    queryFn: ({ signal }) => fetchRegister(systemId!, signal),
    enabled: !!systemId,
    refetchInterval: 30_000,
  });
}

export function useCloseRegisterItem(systemId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ obligationId, reason }: { obligationId: string; reason: string }) =>
      closeRegisterItem(systemId, obligationId, reason),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: registerKeys.system(systemId) });
    },
  });
}

export function useReopenRegisterItem(systemId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ obligationId, reason }: { obligationId: string; reason?: string }) =>
      reopenRegisterItem(systemId, obligationId, reason),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: registerKeys.system(systemId) });
    },
  });
}
