// API calls for the findings register. Hooks (../hooks) wrap these in react-query.
import { api } from '@/shared/lib/api';
import { toRegister, toRegisterItem } from '../lib/register';
import { registerApi } from '../lib/routes';
import type { Register, RegisterItem } from '../lib/types';

export const fetchRegister = (systemId: string, signal?: AbortSignal): Promise<Register> =>
  api.get<unknown>(registerApi.list(systemId), { signal }).then(toRegister);

export const closeRegisterItem = (
  systemId: string,
  obligationId: string,
  reason: string,
): Promise<RegisterItem> =>
  api.post<unknown>(registerApi.close(systemId, obligationId), { reason }).then(toRegisterItem);

export const reopenRegisterItem = (
  systemId: string,
  obligationId: string,
  reason?: string,
): Promise<RegisterItem> =>
  api
    .post<unknown>(registerApi.reopen(systemId, obligationId), { reason: reason || null })
    .then(toRegisterItem);
