import { Play, Plug } from 'lucide-react';
import { useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Button, DropdownMenu, Tooltip, toast } from '@/shared/ui';
import { usePluginGraph } from '../hooks/usePlugins';
import { useStartAudit, useSystemFiles, useSystems } from '../hooks/useSystems';
import { systemRoutes } from '../lib/routes';
import type { PluginGraph } from '../lib/types';

function useStart() {
  const navigate = useNavigate();
  const start = useStartAudit();
  const run = (systemId: string, systemName?: string, plugin?: { folder: string; name: string }) =>
    start.mutate(
      { systemId, systemName, targetPlugin: plugin?.folder },
      {
        onSuccess: (audit) => {
          const what = systemName ?? systemId;
          toast.success(`Audit started: ${plugin ? `${what} · ${plugin.name}` : what}`);
          navigate(`/audits/${encodeURIComponent(audit.id)}`);
        },
        onError: (e) => toast.error('Could not start the audit', { description: (e as Error).message }),
      },
    );
  return { run, pending: start.isPending };
}

interface AuditTarget {
  /** Plugin folder, sent as `target_plugin`. */
  folder: string;
  /** The component it wraps (or the plugin's own name). */
  name: string;
  recommended: boolean;
}

/** The decision model is the one worth auditing first (ranker, scorer, classifier). */
const DECISION_MODEL = /rank|scor|classif|model/i;

/**
 * Plugins an audit can test (configured, with `data/data-dictionary.yaml`: the input fields the
 * agent generates test data for), the decision model first.
 */
export function auditTargets(graph: PluginGraph | undefined, paths: Set<string>): AuditTarget[] {
  if (!graph) return [];
  const byFolder = new Map(graph.components.filter((c) => c.plugin).map((c) => [c.plugin!, c]));
  const auditable = Object.entries(graph.plugins).filter(([folder]) =>
    paths.has(`plugins/${folder}/data/data-dictionary.yaml`),
  );
  const targets = auditable.map(([folder, card]) => ({
    folder,
    name: byFolder.get(folder)?.name || card?.name || folder,
    recommended: false,
  }));
  const pick = targets.find((t) => DECISION_MODEL.test(t.folder));
  if (pick && targets.length > 1) {
    pick.recommended = true;
    targets.splice(targets.indexOf(pick), 1);
    targets.unshift(pick);
  }
  return targets;
}

/**
 * Starts an audit of one system (POST /v1/systems/{id}/audits) and opens it. One audit tests one
 * plugin (model): with several configured plugins the button asks which one.
 */
export function StartAuditButton({ systemId, systemName }: { systemId: string; systemName?: string }) {
  const { run, pending } = useStart();
  const graph = usePluginGraph(systemId);
  const files = useSystemFiles(systemId);
  const targets = useMemo(
    () => auditTargets(graph.data, new Set((files.data ?? []).map((f) => f.path))),
    [graph.data, files.data],
  );
  const loading = graph.isLoading || files.isLoading;

  // Nothing to audit yet: point to the Plugins tab instead of starting an audit that must fail.
  if (!loading && targets.length === 0) {
    const configured = Object.keys(graph.data?.plugins ?? {}).length > 0;
    return (
      <Tooltip
        content={
          configured
            ? 'Its plugins have no data dictionary yet (data/data-dictionary.yaml): add it in the Plugins tab.'
            : 'No model to audit yet: build the pipeline and configure a plugin in the Plugins tab.'
        }
      >
        <Button asChild variant="secondary">
          <Link to={systemRoutes.detail(systemId, 'plugins')}>
            <Plug /> Set up a plugin to audit
          </Link>
        </Button>
      </Tooltip>
    );
  }

  if (targets.length < 2)
    return (
      <Button onClick={() => run(systemId, systemName, targets[0])} loading={pending} disabled={loading}>
        <Play /> Start audit
      </Button>
    );

  return (
    <DropdownMenu
      trigger={
        <Button loading={pending}>
          <Play /> Start audit
        </Button>
      }
      className="min-w-[16rem]"
      items={[
        { type: 'label', label: 'Which model to audit?' },
        ...targets.map((t) => ({
          label: (
            <span className="flex flex-col">
              <span>
                {t.name}
                {t.recommended && (
                  <span className="ml-1.5 text-xs font-medium text-primary">(recommended)</span>
                )}
              </span>
              <span className="font-mono text-[11px] text-muted">plugins/{t.folder}</span>
            </span>
          ),
          onSelect: () => run(systemId, systemName, t),
        })),
      ]}
    />
  );
}

/** "Start audit" with a system picker, for pages without a system in context. */
export function StartAuditMenu() {
  const { data: systems = [] } = useSystems();
  const { run, pending } = useStart();
  return (
    <DropdownMenu
      trigger={
        <Button loading={pending} disabled={systems.length === 0}>
          <Play /> Start audit
        </Button>
      }
      items={[
        { type: 'label', label: 'Audit a system' },
        ...systems.map((s) => ({
          label: `${s.id} · ${s.name}`,
          onSelect: () => run(s.id, s.name),
        })),
      ]}
    />
  );
}
