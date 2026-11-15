import { motion } from 'framer-motion';
import { ChevronRight, ClipboardCheck } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { formatRelative } from '@/shared/lib/format';
import { auditLabel } from '@/shared/lib/labels';
import { listItem, staggerList } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';
import { Card, EmptyState, ErrorState, FilterBar, PageHeader, Skeleton, type Facet } from '@/shared/ui';
import { StartAuditMenu } from '@/features/systems/components/StartAuditButton';
import { FindingsSummary } from '../components/list_parts/FindingsSummary';
import { RunProgress } from '../components/list_parts/RunProgress';
import { useAudits } from '../hooks/useAudits';
import { PHASE_FILTERS, auditPhase, formatRunDate, phaseCounts, verdictBuckets } from '../lib/auditList';

// System · Date/time · Progress · Findings · chevron
const PHASE_DOT = { running: 'bg-primary', waiting: 'bg-warning', done: 'bg-success', failed: 'bg-danger' };

const GRID = 'md:grid-cols-[minmax(0,1.5fr)_120px_minmax(0,1.6fr)_minmax(0,1.3fr)_16px]';

export function AuditsListPage() {
  const { data, isLoading, error, refetch } = useAudits();
  const all = useMemo(() => data ?? [], [data]);
  const [q, setQ] = useState('');
  const [systems, setSystems] = useState<string[]>([]);
  const [phases, setPhases] = useState<string[]>([]);
  const [findings, setFindings] = useState<string[]>([]);
  const counts = useMemo(() => phaseCounts(all), [all]);
  const findingsOf = (a: (typeof all)[number]) => {
    const b = verdictBuckets(a.data);
    if (!b) return 'none';
    return (b.find((x) => x.id === 'gap')?.count ?? 0) > 0 ? 'gaps' : 'clean';
  };
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return all.filter((a) => {
      if (systems.length && !systems.includes(a.systemId)) return false;
      if (phases.length && !phases.includes(auditPhase(a))) return false;
      if (findings.length && !findings.includes(findingsOf(a))) return false;
      if (!needle) return true;
      const hay = [a.id, a.systemId, a.data.systemName, a.data.title, a.data.kbVersion, a.data.trigger]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return hay.includes(needle);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, q, systems, phases, findings]);

  const systemOptions = useMemo(() => {
    const m = new Map<string, { name: string; n: number }>();
    for (const a of all) {
      const cur = m.get(a.systemId) ?? { name: String(a.data.systemName ?? a.systemId), n: 0 };
      m.set(a.systemId, { ...cur, n: cur.n + 1 });
    }
    return [...m.entries()].map(([value, v]) => ({
      value,
      label: (
        <span>
          {v.name} <span className="font-mono text-2xs text-muted">{value}</span>
        </span>
      ),
      count: v.n,
    }));
  }, [all]);
  const findingCounts = useMemo(() => {
    const c = { gaps: 0, clean: 0, none: 0 };
    for (const a of all) c[findingsOf(a) as keyof typeof c] += 1;
    return c;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all]);
  const facets: Facet[] = [
    { id: 'system', label: 'System', options: systemOptions, selected: systems, onChange: setSystems },
    {
      id: 'status',
      label: 'Status',
      options: PHASE_FILTERS.filter((f) => f.id !== 'all' && counts[f.id] > 0).map((f) => ({
        value: f.id,
        label: f.label,
        count: counts[f.id],
        icon: <span className={cn('size-2 rounded-full', PHASE_DOT[f.id as keyof typeof PHASE_DOT])} />,
      })),
      selected: phases,
      onChange: setPhases,
    },
    {
      id: 'findings',
      label: 'Findings',
      options: [
        {
          value: 'gaps',
          label: 'Has gaps',
          count: findingCounts.gaps,
          icon: <span className="size-2 rounded-full bg-danger" />,
        },
        {
          value: 'clean',
          label: 'No gaps',
          count: findingCounts.clean,
          icon: <span className="size-2 rounded-full bg-success" />,
        },
        {
          value: 'none',
          label: 'No findings yet',
          count: findingCounts.none,
          icon: <span className="size-2 rounded-full bg-muted" />,
        },
      ].filter((o) => o.count > 0),
      selected: findings,
      onChange: setFindings,
    },
  ];
  const filterKey = [q, ...systems, '|', ...phases, '|', ...findings].join(',');

  return (
    <div>
      <PageHeader
        title="Audits"
        description="Agent audit runs: context, scenarios, synthetic data, tests, findings and reports."
        actions={<StartAuditMenu />}
      />
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && (
        <Card className="divide-y divide-border">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="flex items-center gap-4 px-4 py-4">
              <div className="flex-1 space-y-1.5">
                <Skeleton className="h-3.5 w-56" />
                <Skeleton className="h-3 w-40" />
              </div>
              <Skeleton className="h-1.5 w-32" />
            </div>
          ))}
        </Card>
      )}
      {data && data.length === 0 && (
        <EmptyState
          icon={<ClipboardCheck />}
          title="No audits yet"
          description="Start an audit of a system: the agent loads its context and plans the tests."
          action={<StartAuditMenu />}
        />
      )}
      {data && data.length > 0 && (
        <div className="space-y-3">
          <FilterBar
            search={{ value: q, onChange: setQ, placeholder: 'Search system, audit id, kb…' }}
            facets={facets}
            summary={
              rows.length === all.length ? `${all.length} audits` : `${rows.length} of ${all.length} audits`
            }
          />
          <Card className="overflow-hidden">
            <div
              className={cn(
                'hidden gap-5 border-b border-border px-5 py-2.5 text-2xs font-medium uppercase tracking-wide text-muted md:grid',
                GRID,
              )}
            >
              <span>System</span>
              <span>Date / time</span>
              <span>Progress</span>
              <span>Findings</span>
              <span />
            </div>
            {rows.length === 0 && (
              <p className="px-5 py-8 text-center text-sm text-muted">No audits match these filters.</p>
            )}
            <motion.ul key={filterKey} variants={staggerList()} initial="initial" animate="animate">
              {rows.map((a) => (
                <motion.li key={a.id} variants={listItem} className="border-b border-border last:border-b-0">
                  <Link
                    to={`/audits/${encodeURIComponent(a.id)}`}
                    className={cn(
                      'group grid grid-cols-2 items-center gap-x-5 gap-y-3 px-5 py-4 transition-colors hover:bg-surface-muted/50',
                      GRID,
                    )}
                  >
                    <div className="col-span-2 min-w-0 md:col-span-1">
                      <div className="flex min-w-0 items-baseline gap-2">
                        <span className="truncate text-sm font-semibold">
                          {a.data.systemName ?? a.systemId}
                        </span>
                        <span className="num shrink-0 text-2xs text-muted">{a.systemId}</span>
                      </div>
                      <div className="mt-0.5 flex min-w-0 items-center gap-2 font-mono text-2xs text-muted">
                        <span className="truncate">{auditLabel(a)}</span>
                        {a.data.kbVersion && <span className="shrink-0">kb {a.data.kbVersion}</span>}
                      </div>
                      {a.data.trigger && a.data.trigger !== 'manual' && (
                        <div className="mt-1 truncate text-2xs text-muted">Triggered by {a.data.trigger}</div>
                      )}
                    </div>
                    <div className="col-span-2 flex min-w-0 items-baseline gap-2 md:col-span-1 md:block">
                      <div className="num text-xs font-medium">{formatRunDate(a.createdAt)}</div>
                      <div className="text-2xs text-muted">{formatRelative(a.createdAt)}</div>
                    </div>
                    <div className="col-span-2 min-w-0 md:col-span-1">
                      <RunProgress audit={a} />
                    </div>
                    <div className="col-span-2 min-w-0 md:col-span-1">
                      <FindingsSummary buckets={auditPhase(a) === 'done' ? verdictBuckets(a.data) : null} />
                    </div>
                    <ChevronRight className="hidden size-4 text-muted opacity-0 transition-opacity group-hover:opacity-100 md:block" />
                  </Link>
                </motion.li>
              ))}
            </motion.ul>
          </Card>
        </div>
      )}
    </div>
  );
}
