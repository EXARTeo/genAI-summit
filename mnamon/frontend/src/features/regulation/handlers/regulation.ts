// Regulation memory calls. reg-memory is internal (port 8010, X-Internal-Secret), so the browser goes
// through backend proxy routes under /v1/regulation (mocked today; backend proxy pending).
import { api } from '@/shared/lib/api';
import type {
  CheckNowResult,
  DemoMirrorEdit,
  DocDiff,
  DocText,
  JudgeDecision,
  Provision,
  ProvisionList,
  RegChange,
  RegSource,
  ReleaseList,
} from '../lib/types';

export const regulationApi = {
  sources: () => api.get<RegSource[]>('/v1/regulation/sources'),
  text: (docId: string, version?: number) =>
    api.get<DocText>(`/v1/regulation/documents/${encodeURIComponent(docId)}/text`, { query: { version } }),
  diff: (docId: string, from: number, to: number) =>
    api.get<DocDiff>(`/v1/regulation/documents/${encodeURIComponent(docId)}/diff`, { query: { from, to } }),
  changes: () => api.get<RegChange[]>('/v1/regulation/changes'),
  releases: () => api.get<ReleaseList>('/v1/regulation/releases'),
  /** reg-memory provisions of the active kb (paged by `offset`; `limit` ≤ 2000). */
  provisions: (query: { limit?: number; offset?: number; instrument?: string; with_text?: boolean }) =>
    api.get<ProvisionList>('/v1/regulation/provisions', { query }),
  provision: (id: string, kbVersion?: string) =>
    api.get<Provision>(`/v1/regulation/provisions/${encodeURIComponent(id)}`, {
      query: { kb_version: kbVersion },
    }),
  decideChange: (id: string, body: { status: 'accepted' | 'rejected' }) =>
    api.post<RegChange>(`/v1/regulation/changes/${encodeURIComponent(id)}/decision`, body),
  overrideJudge: (id: string, systemId: string, decision: JudgeDecision) =>
    api.post<RegChange>(
      `/v1/regulation/changes/${encodeURIComponent(id)}/systems/${encodeURIComponent(systemId)}`,
      { decision },
    ),
  /** Ask reg-memory to re-check every watched source now (queued; changes land in the inbox). */
  checkNow: () => api.post<CheckNowResult>('/v1/regulation/check-now', { wait: false }),
  /** Demo: edit the mirrored guideline page and re-check it at once (a RegChange appears). */
  simulateChange: (body: DemoMirrorEdit) =>
    api.put<{ check?: { release?: { change_id?: string } } } & Record<string, unknown>>(
      '/v1/regulation/demo/mirror',
      body,
    ),
};
