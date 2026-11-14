import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { auditsApi } from '../handlers/audits';
import type { ApprovalIn, AuditDetail } from '../lib/types';

export const auditKeys = {
  all: ['audits'] as const,
  list: (systemId?: string) => ['audits', 'list', systemId ?? 'all'] as const,
  detail: (id: string) => ['audits', 'detail', id] as const,
};

const isLive = (status?: string) => status === 'running' || status === 'open';

export function useAudits(systemId?: string) {
  return useQuery({
    queryKey: auditKeys.list(systemId),
    queryFn: () => auditsApi.list(systemId),
    refetchInterval: (q) => (q.state.data?.some((a) => isLive(a.status)) ? 4000 : 15000),
  });
}

/** Audit detail; polls while the run is live so the Stepper advances on its own. */
export function useAudit(id: string | undefined) {
  return useQuery({
    queryKey: auditKeys.detail(id ?? ''),
    queryFn: () => auditsApi.get(id!),
    enabled: !!id,
    refetchInterval: (q) => (isLive(q.state.data?.status) ? 1500 : false),
  });
}

export function useDecideGate(auditId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ApprovalIn) => auditsApi.decide(auditId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: auditKeys.all });
    },
  });
}

export type { AuditDetail };
