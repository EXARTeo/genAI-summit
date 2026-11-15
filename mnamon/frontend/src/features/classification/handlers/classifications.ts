// API calls for risk classification (backend `router/classifications.py`, plan 02 §7.3).
import { api } from '@/shared/lib/api';
import { systemApi } from '@/features/systems/lib/routes';
import { toClassification, toClassifications } from '../lib/classification';
import type { Classification, ObligationsPreview } from '../lib/types';

export const fetchClassifications = (systemId: string, signal?: AbortSignal): Promise<Classification[]> =>
  api.get<unknown>(systemApi.classifications(systemId), { signal }).then(toClassifications);

/** Start a run (202 + the `running` row). `previousId`: the run it re-does (after a reject or stale). */
export const startClassification = (systemId: string, previousId?: string): Promise<Classification> =>
  api
    .post<unknown>(systemApi.classifications(systemId), previousId ? { previousId } : {})
    .then(toClassification);

export const decideClassification = (
  systemId: string,
  classificationId: string,
  body: { decision: 'approve' | 'reject'; reason?: string },
): Promise<Classification> =>
  api
    .post<unknown>(systemApi.classificationDecision(systemId, classificationId), body)
    .then(toClassification);

export const fetchObligationsPreview = (systemId: string, signal?: AbortSignal) =>
  api.get<ObligationsPreview>(systemApi.obligations(systemId), { signal });
