import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  addComponent,
  fetchPluginDefaults,
  fetchPluginGraph,
  removeComponent,
  savePlugin,
  type ComponentKind,
} from '../handlers/systems';
import type { PluginCard, PluginGraph } from '../lib/types';
import { systemKeys } from './useSystems';

export const pluginKeys = {
  graph: (id: string) => ['systems', id, 'plugin-graph'] as const,
  defaults: (id: string, q: { component?: string; model?: string; name?: string }) =>
    ['systems', id, 'plugin-defaults', q.component ?? '', q.model ?? '', q.name ?? ''] as const,
};

/** The system graph from architecture.yaml, each component joined with its plugin. */
export function usePluginGraph(systemId: string) {
  return useQuery({
    queryKey: pluginKeys.graph(systemId),
    queryFn: ({ signal }) => fetchPluginGraph(systemId, signal),
  });
}

/** Grey defaults for the plugin form: graph placement + what MLflow knows about the model. */
export function usePluginDefaults(
  systemId: string,
  q: { component?: string; model?: string; name?: string } | null,
) {
  return useQuery({
    queryKey: pluginKeys.defaults(systemId, q ?? {}),
    queryFn: ({ signal }) => fetchPluginDefaults(systemId, q!, signal),
    enabled: !!q && !!(q.component || q.model || q.name),
    staleTime: 30_000,
    retry: false,
  });
}

export function useSavePlugin(systemId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      name: string;
      card: PluginCard;
      component?: string | null;
      reason?: string;
      upstream?: string[];
      downstream?: string[];
      copyExampleFiles?: boolean;
    }) =>
      savePlugin(systemId, v.name, {
        card: v.card,
        component: v.component,
        reason: v.reason,
        upstream: v.upstream,
        downstream: v.downstream,
        copy_example_files: v.copyExampleFiles,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: pluginKeys.graph(systemId) });
      void qc.invalidateQueries({ queryKey: ['systems', systemId, 'plugin-defaults'] });
      void qc.invalidateQueries({ queryKey: systemKeys.files(systemId) });
      void qc.invalidateQueries({ queryKey: ['systems', systemId, 'file'] });
      void qc.invalidateQueries({ queryKey: systemKeys.events(systemId) });
    },
  });
}

function useGraphMutation<V>(systemId: string, fn: (v: V) => Promise<PluginGraph>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (graph) => {
      qc.setQueryData(pluginKeys.graph(systemId), graph);
      void qc.invalidateQueries({ queryKey: ['systems', systemId, 'plugin-defaults'] });
      void qc.invalidateQueries({ queryKey: systemKeys.files(systemId) });
      void qc.invalidateQueries({ queryKey: ['systems', systemId, 'file'] });
      void qc.invalidateQueries({ queryKey: systemKeys.events(systemId) });
    },
  });
}

/** Add a box (model, upstream system, human step) to the system graph. */
export function useAddComponent(systemId: string) {
  return useGraphMutation(
    systemId,
    (v: { name: string; kind: ComponentKind; model?: string; upstream?: string[]; downstream?: string[] }) =>
      addComponent(systemId, v),
  );
}

/** Remove a box and its edges from the system graph. */
export function useRemoveComponent(systemId: string) {
  return useGraphMutation(systemId, (componentId: string) => removeComponent(systemId, componentId));
}
