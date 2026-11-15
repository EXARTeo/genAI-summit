import { SearchX } from 'lucide-react';
import { Fragment, useMemo, useState, type KeyboardEvent } from 'react';
import { cn } from '@/shared/lib/utils';
import { Card, EmptyState, Skeleton } from '@/shared/ui';
import { useAuditFindings } from '../hooks/useAudits';
import {
  AI_ACT_CHAPTERS,
  chapterOf,
  filterFindings,
  panelFindings,
  sortFindingsView,
  verdictCounts,
  type SealedFinding,
} from '../lib/findings';
import { TONE_CLASSES, verdictStyle } from '../lib/styling';
import type { AuditDetail } from '../lib/types';
import { DeltaReportCard } from './findings_parts/DeltaReportCard';
import { FindingDetail } from './findings_parts/FindingDetail';
import { FindingRow } from './findings_parts/FindingRow';
import { FindingsSummary } from './findings_parts/FindingsSummary';
import { FindingsToolbar, type FindingsGroup } from './findings_parts/FindingsToolbar';

const SEV_ORDER = ['critical', 'high', 'medium', 'low'];

function groupRows(
  rows: SealedFinding[],
  group: FindingsGroup,
): { key: string; label: string; rows: SealedFinding[] }[] {
  if (group === 'none') return [{ key: 'all', label: '', rows }];
  const m = new Map<string, SealedFinding[]>();
  for (const f of rows) {
    const k = group === 'chapter' ? chapterOf(f) : f.verdict;
    m.set(k, [...(m.get(k) ?? []), f]);
  }
  const keys = [...m.keys()];
  if (group === 'chapter') {
    const order = AI_ACT_CHAPTERS.map((c) => c.label);
    const rank = (k: string) => (order.indexOf(k) < 0 ? order.length : order.indexOf(k));
    keys.sort((a, b) => rank(a) - rank(b));
  }
  return keys.map((k) => ({
    key: k,
    label: group === 'chapter' ? k : verdictStyle(k).label,
    rows: m.get(k) ?? [],
  }));
}

/**
 * The audit's findings: one sealed verdict per obligation (falls back to finding artifacts on older audits).
 * Summary tiles filter by verdict; a dense list on the left, the selected finding's detail on the right
 * (inline under the row below `xl`). No edit controls: findings are only annotated.
 */
export function FindingsPanel({ audit }: { audit: AuditDetail }) {
  const live = audit.status === 'running' || audit.status === 'open';
  const { data, isLoading } = useAuditFindings(audit.id, live);
  const rows = useMemo(
    () => sortFindingsView(panelFindings(data, audit.artifacts, audit.id, audit.systemId)),
    [data, audit.artifacts, audit.id, audit.systemId],
  );
  const [verdicts, setVerdicts] = useState<string[]>([]);
  const [severity, setSeverity] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [group, setGroup] = useState<FindingsGroup>('none');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const visible = useMemo(
    () => filterFindings(rows, { verdicts, severity, query }),
    [rows, verdicts, severity, query],
  );
  const groups = useMemo(() => groupRows(visible, group), [visible, group]);
  const ordered = groups.flatMap((g) => g.rows);
  // Keep a selection while it is visible; otherwise the first visible row (the wide detail pane is never empty).
  const selected =
    ordered.find((f) => f.id === selectedId) ?? (selectedId === '' ? null : (ordered[0] ?? null));
  const counts = useMemo(() => verdictCounts(rows), [rows]);
  const severities = useMemo(() => {
    const present = new Set(rows.map((f) => f.severity ?? 'none'));
    return [...SEV_ORDER, 'none'].filter((s) => present.has(s));
  }, [rows]);

  // A focused re-run after a regulation change: old vs new verdict per obligation.
  const deltas = audit.artifacts.filter((a) => a.kind === 'delta_report' && a.status !== 'superseded');
  const deltaCards = deltas.map((a) => <DeltaReportCard key={a.id} artifact={a} />);

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-36 rounded-xl" />
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-10 rounded-lg" />
        ))}
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div className="space-y-4">
        {deltaCards}
        <Card className="p-2">
          <EmptyState
            title="No findings yet"
            description="Each applicable obligation gets exactly one sealed verdict when the audit reaches its seal step."
          />
        </Card>
      </div>
    );
  }

  const filtered = verdicts.length > 0 || severity != null || query.trim() !== '';
  const clear = () => {
    setVerdicts([]);
    setSeverity(null);
    setQuery('');
  };
  const toggleVerdict = (v: string) =>
    setVerdicts((cur) => (cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]));
  // Click the open row again to fold it (the inline view); '' = nothing selected on purpose.
  const select = (id: string) =>
    setSelectedId((cur) => (cur === id || (cur == null && selected?.id === id) ? '' : id));

  const onListKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const i = selected ? ordered.indexOf(selected) : -1;
    const next = ordered[Math.min(ordered.length - 1, Math.max(0, i + (e.key === 'ArrowDown' ? 1 : -1)))];
    if (!next) return;
    setSelectedId(next.id);
    e.currentTarget.querySelector<HTMLElement>(`[data-finding-row="${next.id}"]`)?.focus();
  };

  return (
    <div className="space-y-4">
      {deltaCards}
      <FindingsSummary rows={rows} counts={counts} selected={verdicts} onToggle={toggleVerdict} />
      <FindingsToolbar
        query={query}
        onQuery={setQuery}
        severity={severity}
        severities={severities}
        onSeverity={setSeverity}
        group={group}
        onGroup={setGroup}
        shown={visible.length}
        total={rows.length}
        filtered={filtered}
        onClear={clear}
      />

      {visible.length === 0 ? (
        <Card className="p-2">
          <EmptyState
            icon={<SearchX />}
            title="No findings match"
            description="Change the search or clear the filters."
          />
        </Card>
      ) : (
        <div className="xl:grid xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] xl:items-start xl:gap-4">
          <Card className="overflow-hidden" onKeyDown={onListKey}>
            {groups.map((g) => (
              <Fragment key={g.key}>
                {g.label && (
                  <div className="flex items-center gap-2 border-b border-border bg-surface-sunken/50 px-4 py-1.5 text-2xs font-semibold uppercase tracking-wider text-muted">
                    {group === 'verdict' && (
                      <span
                        className={cn('size-1.5 rounded-full', TONE_CLASSES[verdictStyle(g.key).tone].dot)}
                      />
                    )}
                    <span className="truncate">{g.label}</span>
                    <span className="num ml-auto font-normal">{g.rows.length}</span>
                  </div>
                )}
                <ul className="divide-y divide-border border-b border-border last:border-b-0">
                  {g.rows.map((f) => {
                    const on = selected?.id === f.id;
                    return (
                      <li key={f.id}>
                        <FindingRow f={f} selected={on} onSelect={() => select(f.id)} />
                        {on && (
                          <div className="border-t border-border bg-surface-sunken/30 px-4 py-4 xl:hidden">
                            <FindingDetail f={f} />
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </Fragment>
            ))}
          </Card>
          <Card className="sticky top-4 hidden max-h-[calc(100vh-2rem)] overflow-y-auto p-5 xl:block">
            {selected ? (
              <FindingDetail key={selected.id} f={selected} />
            ) : (
              <p className="py-10 text-center text-sm text-muted">Select a finding to see its reasoning.</p>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
