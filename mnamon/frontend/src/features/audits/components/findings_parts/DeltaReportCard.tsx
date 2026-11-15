import { ArrowRight, GitCompareArrows } from 'lucide-react';
import { Link } from 'react-router-dom';
import { cn } from '@/shared/lib/utils';
import { Badge, Card } from '@/shared/ui';
import type { Artifact } from '../../lib/types';
import { VerdictPill } from '../artifact_parts/common';

interface Brief {
  verdict?: string;
  severity?: string;
  gap_id?: string;
  kb_version?: string;
}
interface Row {
  obligation_id: string;
  old?: Brief | null;
  new?: Brief | null;
  verdict_changed?: boolean;
  reason?: string;
  metric_deltas?: { metric: string; old?: number | null; new?: number | null; delta?: number | null }[];
}
interface Delta {
  change_id?: string;
  previous_audit_id?: string;
  from_kb_version?: string;
  to_kb_version?: string;
  model_version?: { old?: string | null; new?: string | null };
  obligations?: Row[];
  summary?: string;
}

const REASON: Record<string, string> = {
  law_changed: 'law changed',
  model_changed: 'model changed',
  law_and_model_changed: 'law and model changed',
  new_evidence: 'new evidence',
  no_new_verdict: 'not re-assessed',
  not_assessed: 'not assessed',
  unchanged: 'unchanged',
};

const fmt = (v: number | null | undefined) => (v == null ? '–' : String(Number(v.toFixed(4))));

/** The focused re-run's delta report (agents `change_judge.build_delta_report`): old vs new verdict per obligation. */
export function DeltaReportCard({ artifact }: { artifact: Artifact }) {
  const d = artifact.data as Delta;
  const rows = Array.isArray(d.obligations) ? d.obligations : [];
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-4 py-3">
        <GitCompareArrows className="size-4 text-primary" />
        <h2 className="text-sm font-semibold">Delta report</h2>
        {d.change_id && <Badge className="font-mono">{d.change_id}</Badge>}
        {(d.from_kb_version || d.to_kb_version) && (
          <span className="num font-mono text-2xs text-muted">
            kb {d.from_kb_version ?? '–'} → {d.to_kb_version ?? '–'}
          </span>
        )}
        {d.previous_audit_id && (
          <Link
            to={`/audits/${encodeURIComponent(d.previous_audit_id)}?view=findings`}
            className="ml-auto text-xs text-muted hover:text-text hover:underline"
          >
            vs {d.previous_audit_id}
          </Link>
        )}
      </div>
      {d.summary && <p className="px-4 pt-3 text-sm">{d.summary}</p>}
      <ul className="divide-y divide-border">
        {rows.map((r) => (
          <li key={r.obligation_id} className={cn('px-4 py-3', r.verdict_changed && 'bg-warning/5')}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 flex-1 font-mono text-xs [overflow-wrap:anywhere]">
                {r.obligation_id}
              </span>
              {r.old?.verdict ? (
                <VerdictPill verdict={r.old.verdict} />
              ) : (
                <span className="text-xs text-muted">–</span>
              )}
              <ArrowRight className="size-3.5 text-muted" />
              {r.new?.verdict ? (
                <VerdictPill verdict={r.new.verdict} />
              ) : (
                <span className="text-xs text-muted">–</span>
              )}
              {r.reason && (
                <Badge tone={r.verdict_changed ? 'warning' : 'neutral'}>{REASON[r.reason] ?? r.reason}</Badge>
              )}
            </div>
            {(r.metric_deltas?.length ?? 0) > 0 && (
              <div className="num mt-1.5 flex flex-wrap gap-x-4 gap-y-1 font-mono text-2xs text-muted">
                {r.metric_deltas!.map((m) => (
                  <span key={m.metric}>
                    {m.metric} {fmt(m.old)} → <span className="text-text">{fmt(m.new)}</span>
                    {m.delta != null && (
                      <span>
                        {' '}
                        ({m.delta > 0 ? '+' : ''}
                        {fmt(m.delta)})
                      </span>
                    )}
                  </span>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
