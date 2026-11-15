import { Lock } from 'lucide-react';
import { cn } from '@/shared/lib/utils';
import { Card, EmptyState, Skeleton } from '@/shared/ui';
import { useAuditFindings } from '../hooks/useAudits';
import { panelFindings, sortFindings } from '../lib/findings';
import { TONE_CLASSES, verdictStyle } from '../lib/styling';
import type { AuditDetail } from '../lib/types';
import { DeltaReportCard } from './findings_parts/DeltaReportCard';
import { SealedFindingCard } from './findings_parts/SealedFindingCard';

/** The audit's findings: one sealed verdict per obligation (falls back to finding artifacts on older audits). No edit controls. */
export function FindingsPanel({ audit }: { audit: AuditDetail }) {
  const live = audit.status === 'running' || audit.status === 'open';
  const { data, isLoading } = useAuditFindings(audit.id, live);
  const rows = sortFindings(panelFindings(data, audit.artifacts, audit.id, audit.systemId));
  const sealed = rows.some((r) => r.sealed);
  // A focused re-run after a regulation change: old vs new verdict per obligation.
  const deltas = audit.artifacts.filter((a) => a.kind === 'delta_report' && a.status !== 'superseded');
  const deltaCards = deltas.map((a) => <DeltaReportCard key={a.id} artifact={a} />);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-20 rounded-lg" />
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
  const counts = rows.reduce<Record<string, number>>(
    (m, f) => ({ ...m, [f.verdict]: (m[f.verdict] ?? 0) + 1 }),
    {},
  );

  return (
    <div className="space-y-4">
      {deltaCards}
      <div className="flex flex-wrap items-center gap-2">
        {Object.entries(counts).map(([v, n]) => {
          const st = verdictStyle(v);
          return (
            <span
              key={v}
              className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1 text-xs"
            >
              <span className={cn('size-1.5 rounded-full', TONE_CLASSES[st.tone].dot)} />
              <span className="num font-semibold">{n}</span>
              <span className="text-muted">{st.label}</span>
            </span>
          );
        })}
        <span className="ml-auto inline-flex items-center gap-1.5 text-xs text-muted">
          <Lock className="size-3.5" />
          {sealed
            ? 'Sealed: verdicts never change. Annotate to contest or accept a risk.'
            : 'Older audit: findings shown from its artifacts (not sealed).'}
        </span>
      </div>
      <div className="flex h-1.5 overflow-hidden rounded-full" aria-hidden>
        {rows.map((f) => (
          <span
            key={f.id}
            className={cn(
              'h-full flex-1 border-r-2 border-surface last:border-r-0',
              TONE_CLASSES[verdictStyle(f.verdict).tone].bg,
            )}
          />
        ))}
      </div>
      <div className="space-y-2">
        {rows.map((f, i) => (
          <SealedFindingCard key={f.id} f={f} defaultOpen={i === 0} />
        ))}
      </div>
    </div>
  );
}
