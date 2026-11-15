import { ArrowUpRight, History, ListChecks } from 'lucide-react';
import { Link } from 'react-router-dom';
import { VerdictPill } from '@/features/audits/components/artifact_parts/common';
import { useAudit, useAudits, useSystemFindings } from '@/features/audits/hooks/useAudits';
import {
  articleOf,
  obligationEntries,
  obligationMapArtifact,
  type ObligationEntry,
  type SealedFinding,
} from '@/features/audits/lib/findings';
import { auditLabel } from '@/shared/lib/labels';
import { cn } from '@/shared/lib/utils';
import { Badge, Card, EmptyState, SkeletonText, Tooltip } from '@/shared/ui';
import { ObligationsPreview } from '@/features/classification/components/ObligationsPreview';

const MODE_LABEL: Record<string, string> = {
  test: 'Tested on the model',
  testing: 'Tested on the model',
  model_test: 'Tested on the model',
  documentary: 'Documentation review',
  documentation: 'Documentation review',
  process: 'Process review',
  declared_config: 'Declared config',
};

/** Article label: the map's own, else derived from the id (`OBL.AIA.10.2.f…` → Art. 10(2)(f)). */
function label(e: ObligationEntry): string {
  return e.article ?? articleOf({ obligation_id: e.obligation_id, data: {} }) ?? e.title ?? e.obligation_id;
}

function modeLabel(m: string | null | undefined): string {
  return m ? (MODE_LABEL[m] ?? m.replace(/_/g, ' ')) : '–';
}

function Applies({ e }: { e: ObligationEntry }) {
  if (e.applicable == null) return <Badge>unknown</Badge>;
  return e.applicable ? <Badge tone="primary">Applies</Badge> : <Badge>Not applicable</Badge>;
}

function InForce({ e }: { e: ObligationEntry }) {
  return (
    <span className="num inline-flex items-center gap-1.5 whitespace-nowrap font-mono text-xs">
      {e.in_force_date ?? '–'}
      {e.in_force_now != null && (
        <span className={cn('font-sans text-2xs', e.in_force_now ? 'text-success' : 'text-muted')}>
          {e.in_force_now ? 'in force' : 'not yet'}
        </span>
      )}
    </span>
  );
}

function Latest({ f }: { f: SealedFinding | undefined }) {
  if (!f) return <span className="text-xs text-muted">no verdict yet</span>;
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <VerdictPill verdict={f.verdict} />
      {f.stale && (
        <Tooltip content="A regulation change touched this obligation since the verdict was sealed.">
          <span className="inline-flex">
            <Badge tone="warning" icon={<History />}>
              Stale
            </Badge>
          </span>
        </Tooltip>
      )}
    </span>
  );
}

/**
 * Read-only obligation map of the system (plan 01 §12): which provider obligations apply and
 * why, from the latest audit's `obligation_map` artifact, joined with the current sealed verdicts.
 */
export function ObligationsTab({ systemId }: { systemId: string }) {
  const audits = useAudits(systemId);
  const latest = [...(audits.data ?? [])].sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0];
  const detail = useAudit(latest?.id);
  const findings = useSystemFindings(systemId);

  if (audits.isLoading || (latest && detail.isLoading)) {
    return (
      <Card className="p-5">
        <SkeletonText lines={6} />
      </Card>
    );
  }
  const map = detail.data ? obligationMapArtifact(detail.data.artifacts) : null;
  const entries = map ? obligationEntries(map.data) : [];
  const byObligation = new Map<string, SealedFinding>();
  for (const f of findings.data ?? [])
    if (!byObligation.has(f.obligation_id)) byObligation.set(f.obligation_id, f);

  if (!latest || entries.length === 0) {
    // No audit yet: preview the obligations of the approved classification (plan 02 §5), if any.
    return (
      <ObligationsPreview
        systemId={systemId}
        fallback={
          <Card className="p-2">
            <EmptyState
              icon={<ListChecks />}
              title="No obligation map yet"
              description="An audit maps the provider obligations that apply to this system (role, classification, Annex III point, features, date). Approve a risk classification for a preview, or start an audit."
            />
          </Card>
        }
      />
    );
  }
  const applicable = entries.filter((e) => e.applicable).length;
  const stale = entries.filter((e) => byObligation.get(e.obligation_id)?.stale).length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span>
          <span className="num font-semibold">{applicable}</span>
          <span className="text-muted"> of {entries.length} obligations apply</span>
        </span>
        {stale > 0 && (
          <span className="text-warning">
            <span className="num font-semibold">{stale}</span> stale
          </span>
        )}
        <Link
          to={`/audits/${encodeURIComponent(latest.id)}?view=findings`}
          className="ml-auto inline-flex items-center gap-1 text-xs text-muted hover:text-text"
        >
          From {auditLabel(latest)} <ArrowUpRight className="size-3" />
        </Link>
      </div>

      {/* Wide: a table. */}
      <Card className="hidden overflow-hidden lg:block">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-surface-muted/50 text-xs text-muted">
            <tr>
              {['Obligation', 'Applies?', 'Why', 'In force from', 'Verification', 'Latest verdict'].map(
                (h) => (
                  <th key={h} className="whitespace-nowrap px-4 py-2.5 font-medium">
                    {h}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {entries.map((e) => (
              <tr key={e.obligation_id} className={cn('align-top', e.applicable === false && 'text-muted')}>
                <td className="px-4 py-3">
                  <div className="font-medium text-text">{label(e)}</div>
                  {e.title && label(e) !== e.title && <div className="text-xs text-muted">{e.title}</div>}
                  <div className="font-mono text-2xs text-muted">{e.obligation_id}</div>
                </td>
                <td className="px-4 py-3">
                  <Applies e={e} />
                </td>
                <td className="max-w-md px-4 py-3 text-xs">
                  {e.reason ?? '–'}
                  {e.decided_by && (
                    <div className="mt-0.5 text-2xs text-muted">decided by {e.decided_by}</div>
                  )}
                </td>
                <td className="px-4 py-3">
                  <InForce e={e} />
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-xs">{modeLabel(e.verification_mode)}</td>
                <td className="px-4 py-3">
                  {e.applicable === false ? (
                    <span className="text-xs">–</span>
                  ) : (
                    <Latest f={byObligation.get(e.obligation_id)} />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {/* Narrow: one card per obligation. */}
      <ul className="space-y-2 lg:hidden">
        {entries.map((e) => (
          <li key={e.obligation_id}>
            <Card className={cn('space-y-2 p-4', e.applicable === false && 'opacity-80')}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-sm font-medium">{label(e)}</div>
                  {e.title && label(e) !== e.title && <div className="text-xs text-muted">{e.title}</div>}
                  <div className="font-mono text-2xs text-muted [overflow-wrap:anywhere]">
                    {e.obligation_id}
                  </div>
                </div>
                <Applies e={e} />
              </div>
              {e.reason && <p className="text-xs text-muted">{e.reason}</p>}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
                <InForce e={e} />
                <span className="text-muted">{modeLabel(e.verification_mode)}</span>
                {e.applicable !== false && <Latest f={byObligation.get(e.obligation_id)} />}
              </div>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
