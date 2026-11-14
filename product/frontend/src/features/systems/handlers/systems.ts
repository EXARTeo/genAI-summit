// API calls for the systems feature. Hooks (../hooks) wrap these in react-query.
import { api } from '@/shared/lib/api';
import { systemApi } from '../lib/routes';
import type { FileEvent, FileWriteResult, System, WorkspaceFile, WorkspaceFileContent } from '../lib/types';

export const fetchSystems = (signal?: AbortSignal) => api.get<System[]>(systemApi.list(), { signal });

export const fetchSystem = (id: string, signal?: AbortSignal) =>
  api.get<System>(systemApi.get(id), { signal });

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

/** A human-proposed business rule: an inactive memory proposal until approved. */
export function proposeRule(systemId: string, slug: string, yamlText: string, reason: string) {
  return api.put<FileWriteResult>(systemApi.ruleProposal(systemId, slug), {
    content: yamlText,
    contentType: 'application/yaml',
    reason,
  });
}
