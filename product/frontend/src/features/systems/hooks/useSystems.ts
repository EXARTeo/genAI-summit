import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  fetchFile,
  fetchFileEvents,
  fetchFiles,
  fetchFileVersions,
  fetchSystem,
  fetchSystems,
  proposeRule,
  uploadFile,
} from '../handlers/systems';

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

export function useProposeRule(systemId: string) {
  return useMutation({
    mutationFn: (v: { slug: string; yaml: string; reason: string }) =>
      proposeRule(systemId, v.slug, v.yaml, v.reason),
  });
}
