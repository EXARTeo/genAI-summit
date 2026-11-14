import { useQueries } from '@tanstack/react-query';
import { useMemo } from 'react';
import { parse } from 'yaml';
import { fetchFile } from '../handlers/systems';
import { parseBusinessRules } from '../lib/rules';
import type { BusinessRule, PluginCard } from '../lib/types';
import { systemKeys, useSystemFiles } from './useSystems';

function safeYaml<T>(text: string | null | undefined): T | null {
  if (!text) return null;
  try {
    return parse(text) as T;
  } catch {
    return null;
  }
}

/** Every plugin.yaml in the system folder, parsed. */
export function usePlugins(systemId: string) {
  const files = useSystemFiles(systemId);
  const paths = useMemo(
    () => (files.data ?? []).map((f) => f.path).filter((p) => /^plugins\/[^/]+\/plugin\.ya?ml$/.test(p)),
    [files.data],
  );
  const results = useQueries({
    queries: paths.map((p) => ({
      queryKey: systemKeys.file(systemId, p),
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchFile(systemId, p, undefined, signal),
      staleTime: 60_000,
    })),
  });
  const plugins = results
    .map((r, i) => {
      const card = safeYaml<PluginCard>(r.data?.text);
      return card ? { ...card, folder: paths[i].split('/')[1] } : null;
    })
    .filter((p): p is PluginCard & { folder: string } => !!p);
  return {
    plugins,
    isLoading: files.isLoading || results.some((r) => r.isLoading),
    error: files.error ?? results.find((r) => r.error)?.error ?? null,
    refetch: files.refetch,
  };
}

/** Business rules from each plugin's data/business-rules.md. */
export function useBusinessRules(systemId: string) {
  const files = useSystemFiles(systemId);
  const paths = useMemo(
    () =>
      (files.data ?? [])
        .map((f) => f.path)
        .filter((p) => /^plugins\/[^/]+\/data\/business-rules\.md$/.test(p)),
    [files.data],
  );
  const results = useQueries({
    queries: paths.map((p) => ({
      queryKey: systemKeys.file(systemId, p),
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchFile(systemId, p, undefined, signal),
      staleTime: 60_000,
    })),
  });
  const rules: BusinessRule[] = results.flatMap((r, i) =>
    r.data?.text ? parseBusinessRules(r.data.text, paths[i].split('/')[1]) : [],
  );
  return {
    rules,
    plugins: paths.map((p) => p.split('/')[1]),
    isLoading: files.isLoading || results.some((r) => r.isLoading),
    error: files.error ?? results.find((r) => r.error)?.error ?? null,
    refetch: files.refetch,
  };
}
