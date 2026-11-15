// API calls for the systems feature. Hooks (../hooks) wrap these in react-query.
import { api } from '@/shared/lib/api';
import type { Audit } from '@/features/audits/lib/types';
import { toSystem, toSystems } from '../lib/adapters';
import { systemApi } from '../lib/routes';
import type {
  FileEvent,
  FileWriteResult,
  PluginCard,
  PluginDefaults,
  PluginGraph,
  PluginWriteResult,
  System,
  WorkspaceFile,
  WorkspaceFileContent,
} from '../lib/types';

export const fetchSystems = (signal?: AbortSignal) =>
  api.get<System[]>(systemApi.list(), { signal }).then(toSystems);

export const fetchSystem = (id: string, signal?: AbortSignal) =>
  api.get<System>(systemApi.get(id), { signal }).then(toSystem);

/** Start an audit of the system (POST /v1/systems/{id}/audits); the pipeline runs in the background. */
export const startAudit = (id: string, body: { stage?: string; data?: Record<string, unknown> }) =>
  api.post<Audit>(systemApi.audits(id), body);

export const fetchFiles = (id: string, signal?: AbortSignal) =>
  api.get<WorkspaceFile[]>(systemApi.files(id), { signal });

export const fetchFile = (id: string, path: string, version?: number, signal?: AbortSignal) =>
  api.get<WorkspaceFileContent>(systemApi.file(id, path), { query: { format: 'json', version }, signal });

export const fetchFileVersions = (id: string, path: string, signal?: AbortSignal) =>
  api.get<WorkspaceFile[]>(systemApi.versions(id, path), { signal });

export const fetchFileEvents = (id: string, signal?: AbortSignal) =>
  api.get<FileEvent[]>(systemApi.events(id), { signal, query: { limit: 100 } });

/** Upload one file (multipart) into the system folder; returns the new version. */
export function uploadFile(id: string, path: string, file: File, reason?: string) {
  const form = new FormData();
  form.append('file', file);
  if (reason) form.append('reason', reason);
  return api.put<FileWriteResult>(systemApi.file(id, path), form);
}

export function writeTextFile(id: string, path: string, content: string, reason?: string) {
  return api.put<FileWriteResult>(systemApi.file(id, path), { content, reason });
}

/** The system graph (architecture.yaml) with each component's plugin. */
export const fetchPluginGraph = (id: string, signal?: AbortSignal) =>
  api.get<PluginGraph>(systemApi.plugins(id), { signal });

/** Defaults for the plugin form (graph placement + the local MLflow registry). */
export const fetchPluginDefaults = (
  id: string,
  q: { component?: string; model?: string; name?: string },
  signal?: AbortSignal,
) => api.get<PluginDefaults>(systemApi.pluginDefaults(id), { query: q, signal });

/** Save a plugin: a new version of plugins/<name>/plugin.yaml. */
export const savePlugin = (
  id: string,
  name: string,
  body: {
    card: PluginCard;
    component?: string | null;
    reason?: string;
    upstream?: string[];
    downstream?: string[];
    copy_example_files?: boolean;
  },
) => api.put<PluginWriteResult>(systemApi.plugin(id, name), body);

export type ComponentKind = 'ml_model' | 'upstream_system' | 'human_review';

/** Add a box to the system graph (architecture.yaml); returns the new graph. */
export const addComponent = (
  id: string,
  body: {
    name: string;
    kind: ComponentKind;
    model?: string;
    note?: string;
    upstream?: string[];
    downstream?: string[];
  },
) => api.post<PluginGraph>(systemApi.components(id), body);

/** Remove a box and its edges from the graph (its plugin files stay). */
export const removeComponent = (id: string, componentId: string) =>
  api.delete<PluginGraph>(systemApi.component(id, componentId));
