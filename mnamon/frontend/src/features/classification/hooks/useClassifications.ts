import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { systemKeys } from '@/features/systems/hooks/useSystems';
import {
  decideClassification,
  fetchClassifications,
  fetchObligationsPreview,
  startClassification,
} from '../handlers/classifications';
import { isRunning } from '../lib/classification';

export const classificationKeys = {
  system: (systemId: string) => ['classifications', systemId] as const,
  obligations: (systemId: string) => ['classifications', systemId, 'obligations'] as const,
};

/** Every run of the system, newest first; polls every 2 s while one is running. */
export function useClassifications(systemId: string) {
  return useQuery({
    queryKey: classificationKeys.system(systemId),
    queryFn: ({ signal }) => fetchClassifications(systemId, signal),
    enabled: !!systemId,
    refetchInterval: (q) => (q.state.data && isRunning(q.state.data) ? 2_000 : false),
  });
}

export function useStartClassification(systemId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (previousId?: string) => startClassification(systemId, previousId),
    onSuccess: () => qc.invalidateQueries({ queryKey: classificationKeys.system(systemId) }),
  });
}

/** Approve or reject a proposal; an approval rewrites the card, so the system is refetched too. */
export function useDecideClassification(systemId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; decision: 'approve' | 'reject'; reason?: string }) =>
      decideClassification(systemId, v.id, { decision: v.decision, reason: v.reason }),
    onSuccess: (_r, v) => {
      void qc.invalidateQueries({ queryKey: classificationKeys.system(systemId) });
      if (v.decision === 'approve') {
        void qc.invalidateQueries({ queryKey: systemKeys.all });
        void qc.invalidateQueries({ queryKey: systemKeys.detail(systemId) });
        void qc.invalidateQueries({ queryKey: classificationKeys.obligations(systemId) });
      }
    },
  });
}

export function useObligationsPreview(systemId: string, enabled: boolean) {
  return useQuery({
    queryKey: classificationKeys.obligations(systemId),
    queryFn: ({ signal }) => fetchObligationsPreview(systemId, signal),
    enabled: !!systemId && enabled,
    retry: false,
  });
}
