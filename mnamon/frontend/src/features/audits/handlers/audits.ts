// Typed calls to the backend audits API (`/v1/audits`, see mnamon/backend/router/audits.py).
import { api } from '@/shared/lib/api';
import type { Annotation, AnnotationIn, SealedFinding } from '../lib/findings';
import type { ApprovalIn, ApprovalResult, Approval, Audit, AuditDetail, AuditStatus } from '../lib/types';

const enc = encodeURIComponent;

export const auditsApi = {
  list: (systemId?: string) => api.get<Audit[]>('/v1/audits', { query: { systemId } }),
  get: (id: string) => api.get<AuditDetail>(`/v1/audits/${encodeURIComponent(id)}`),
  update: (id: string, patch: { status?: AuditStatus; stage?: string; data?: Record<string, unknown> }) =>
    api.patch<Audit>(`/v1/audits/${encodeURIComponent(id)}`, patch),
  approvals: (id: string) => api.get<Approval[]>(`/v1/audits/${encodeURIComponent(id)}/approvals`),
  decide: (id: string, body: ApprovalIn) =>
    api.post<ApprovalResult>(`/v1/audits/${encodeURIComponent(id)}/approvals`, body),
  /** Retry a failed audit: the pipeline re-runs the failed step (202). */
  retry: (id: string) =>
    api.post<{ auditId: string; outcome: string; status: AuditStatus }>(`/v1/audits/${enc(id)}/retry`),
  /** The audit's sealed findings (empty for audits sealed before plan 01). */
  findings: (id: string) => api.get<SealedFinding[]>(`/v1/audits/${enc(id)}/findings`),
  systemFindings: (systemId: string, current = true) =>
    api.get<SealedFinding[]>(`/v1/systems/${enc(systemId)}/findings`, { query: { current } }),
  annotate: (findingId: string, body: AnnotationIn) =>
    api.post<Annotation>(`/v1/findings/${enc(findingId)}/annotations`, body),
  /** One system-folder file at the version the audit pinned (the "Files read" preview). */
  systemFile: (systemId: string, path: string, version?: number) =>
    api.get<{ text: string | null; dataB64: string | null; contentType: string; size: number }>(
      `/v1/systems/${encodeURIComponent(systemId)}/files/${path.split('/').map(encodeURIComponent).join('/')}`,
      { query: { format: 'json', version } },
    ),
};
