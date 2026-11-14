import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  fetchFile,
  fetchFileEvents,
  fetchFiles,
  fetchFileVersions,
  fetchSystem,
  fetchSystems,
  startAudit,
  writeTextFile,
  uploadFile,
} from '../handlers/systems';
import { appendRule, businessRulesPath } from '../lib/rules';
import type { BusinessRule } from '../lib/types';

export const systemKeys = {
  all: ['systems'] as const,
  detail: (id: string) => ['systems', id] as const,
  files: (id: string) => ['systems', id, 'files'] as const,
  file: (id: string, path: string, version?: number) =>
    ['systems', id, 'file', path, version ?? 'current'] as const,
  versions: (id: string, path: string) => ['systems', id, 'versions', path] as const,
  events: (id: string) => ['systems', id, 'events'] as const,
};

export function useSystems(opts: { enabled?: boolean } = {}) {
  return useQuery({ queryKey: systemKeys.all, queryFn: ({ signal }) => fetchSystems(signal), ...opts });
}

export function useSystem(id: string) {
  return useQuery({ queryKey: systemKeys.detail(id), queryFn: ({ signal }) => fetchSystem(id, signal) });
}

export function useSystemFiles(id: string) {
  return useQuery({ queryKey: systemKeys.files(id), queryFn: ({ signal }) => fetchFiles(id, signal) });
}

export function useSystemFile(id: string, path: string | null, version?: number) {
  return useQuery({
    queryKey: systemKeys.file(id, path ?? '', version),
    queryFn: ({ signal }) => fetchFile(id, path!, version, signal),
    enabled: !!path,
    staleTime: 60_000,
  });
}

export function useFileVersions(id: string, path: string | null) {
  return useQuery({
    queryKey: systemKeys.versions(id, path ?? ''),
    queryFn: ({ signal }) => fetchFileVersions(id, path!, signal),
    enabled: !!path,
  });
}

export function useFileEvents(id: string) {
  return useQuery({ queryKey: systemKeys.events(id), queryFn: ({ signal }) => fetchFileEvents(id, signal) });
}

export function useUploadFiles(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ files, folder }: { files: File[]; folder: string }) => {
      const prefix = folder.replace(/^\/+|\/+$/g, '');
      return Promise.all(
        files.map((f) => uploadFile(id, prefix ? `${prefix}/${f.name}` : f.name, f, 'uploaded in the UI')),
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: systemKeys.files(id) });
      qc.invalidateQueries({ queryKey: systemKeys.events(id) });
    },
  });
}

/** Append a business rule to the plugin's data/business-rules.md (a new file version). */
export function useAddRule(systemId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { plugin: string; kind: BusinessRule['kind']; text: string; reason: string }) => {
      const path = businessRulesPath(v.plugin);
      const current = await fetchFile(systemId, path);
      return writeTextFile(systemId, path, appendRule(current.text ?? '', v.kind, v.text), v.reason);
    },
    onSuccess: (_res, v) => {
      qc.invalidateQueries({ queryKey: ['systems', systemId, 'file', businessRulesPath(v.plugin)] });
      qc.invalidateQueries({ queryKey: systemKeys.versions(systemId, businessRulesPath(v.plugin)) });
      qc.invalidateQueries({ queryKey: systemKeys.files(systemId) });
      qc.invalidateQueries({ queryKey: systemKeys.events(systemId) });
    },
  });
}

/** Start an audit of a system; the new audit is returned (navigate to it). */
export function useStartAudit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { systemId: string; systemName?: string }) =>
      startAudit(v.systemId, {
        stage: 'load_context',
        data: { title: 'Audit', systemName: v.systemName ?? v.systemId, trigger: 'manual' },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['audits'] });
    },
  });
}
