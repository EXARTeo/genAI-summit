import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { auditsApi } from '../handlers/audits';
import type { AnnotationIn } from '../lib/findings';
import type { ApprovalIn, AuditDetail } from '../lib/types';

export const auditKeys = {
  all: ['audits'] as const,
  list: (systemId?: string) => ['audits', 'list', systemId ?? 'all'] as const,
  detail: (id: string) => ['audits', 'detail', id] as const,
  findings: (id: string) => ['audits', 'findings', id] as const,
  systemFindings: (systemId: string) => ['audits', 'system-findings', systemId] as const,
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

/** The audit's sealed findings; polls while the run is live. */
export function useAuditFindings(id: string | undefined, live = false) {
  return useQuery({
    queryKey: auditKeys.findings(id ?? ''),
    queryFn: () => auditsApi.findings(id!),
    enabled: !!id,
    refetchInterval: live ? 4000 : false,
  });
}

/** A system's current (not superseded) sealed findings. */
export function useSystemFindings(systemId: string | undefined) {
  return useQuery({
    queryKey: auditKeys.systemFindings(systemId ?? ''),
    queryFn: () => auditsApi.systemFindings(systemId!),
    enabled: !!systemId,
  });
}

export function useRetryAudit(auditId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => auditsApi.retry(auditId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: auditKeys.all });
    },
  });
}

export function useAnnotateFinding(auditId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ findingId, body }: { findingId: string; body: AnnotationIn }) =>
      auditsApi.annotate(findingId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: auditKeys.findings(auditId) });
    },
  });
}

export type { AuditDetail };
