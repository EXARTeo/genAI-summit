// Typed calls to the backend audits API (`/v1/audits`, see mnamon/backend/router/audits.py).
import { api } from '@/shared/lib/api';
import type { ApprovalIn, ApprovalResult, Approval, Audit, AuditDetail, AuditStatus } from '../lib/types';

export const auditsApi = {
  list: (systemId?: string) => api.get<Audit[]>('/v1/audits', { query: { systemId } }),
  get: (id: string) => api.get<AuditDetail>(`/v1/audits/${encodeURIComponent(id)}`),
  update: (id: string, patch: { status?: AuditStatus; stage?: string; data?: Record<string, unknown> }) =>
    api.patch<Audit>(`/v1/audits/${encodeURIComponent(id)}`, patch),
  approvals: (id: string) => api.get<Approval[]>(`/v1/audits/${encodeURIComponent(id)}/approvals`),
  decide: (id: string, body: ApprovalIn) =>
    api.post<ApprovalResult>(`/v1/audits/${encodeURIComponent(id)}/approvals`, body),
  /** One system-folder file at the version the audit pinned (the "Files read" preview). */
  systemFile: (systemId: string, path: string, version?: number) =>
    api.get<{ text: string | null; dataB64: string | null; contentType: string; size: number }>(
      `/v1/systems/${encodeURIComponent(systemId)}/files/${path.split('/').map(encodeURIComponent).join('/')}`,
      { query: { format: 'json', version } },
    ),
};
