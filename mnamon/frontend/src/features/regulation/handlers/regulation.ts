// Regulation memory calls. reg-memory is internal (port 8010, X-Internal-Secret), so the browser goes
// through backend proxy routes under /v1/regulation (mocked today; backend proxy pending).
import { api } from '@/shared/lib/api';
import type { CheckNowResult, DocDiff, DocText, JudgeDecision, RegChange, RegSource } from '../lib/types';

export const regulationApi = {
  sources: () => api.get<RegSource[]>('/v1/regulation/sources'),
  text: (docId: string, version?: number) =>
    api.get<DocText>(`/v1/regulation/documents/${encodeURIComponent(docId)}/text`, { query: { version } }),
  diff: (docId: string, from: number, to: number) =>
    api.get<DocDiff>(`/v1/regulation/documents/${encodeURIComponent(docId)}/diff`, { query: { from, to } }),
  changes: () => api.get<RegChange[]>('/v1/regulation/changes'),
  decideChange: (id: string, body: { status: 'accepted' | 'rejected' }) =>
    api.post<RegChange>(`/v1/regulation/changes/${encodeURIComponent(id)}/decision`, body),
  overrideJudge: (id: string, systemId: string, decision: JudgeDecision) =>
    api.post<RegChange>(
      `/v1/regulation/changes/${encodeURIComponent(id)}/systems/${encodeURIComponent(systemId)}`,
      { decision },
    ),
  /** Ask reg-memory to re-check every watched source now (queued; changes land in the inbox). */
  checkNow: () => api.post<CheckNowResult>('/v1/regulation/check-now', { wait: false }),
};
