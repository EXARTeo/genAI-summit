// Typed calls to the backend audits API (`/v1/audits`, see product/backend/router/audits.py).
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
};
