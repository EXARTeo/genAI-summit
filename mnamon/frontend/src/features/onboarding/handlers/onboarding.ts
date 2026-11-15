// API calls for registering a system (existing backend routes: POST /v1/systems + folder files).
import { api } from '@/shared/lib/api';
import { uploadFile, writeTextFile } from '@/features/systems/handlers/systems';
import { toSystem } from '@/features/systems/lib/adapters';
import { systemApi } from '@/features/systems/lib/routes';
import type { System } from '@/features/systems/lib/types';

export const createSystem = (body: {
  id: string;
  name: string;
  status: string;
  data: Record<string, unknown>;
}) => api.post<System>(systemApi.list(), body).then(toSystem);

export { uploadFile, writeTextFile };
