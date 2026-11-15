import { Ban, ListChecks } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';
import { Badge, Card, EmptyState, ErrorState, SkeletonText } from '@/shared/ui';
import { useClassifications, useObligationsPreview } from '../hooks/useClassifications';
import { inForce, previewEntries, riskLabel } from '../lib/classification';

/**
 * Obligations tab without an audit (plan 02 §5): the obligations reg-memory activates for the
 * system card, from the approved classification when there is one (else the card's declared
 * class, e.g. a seeded system). `fallback` is shown for an unclassified card.
 */
export function ObligationsPreview({ systemId, fallback }: { systemId: string; fallback: ReactNode }) {
  const runs = useClassifications(systemId);
  const approved = inForce(runs.data ?? []);
  const preview = useObligationsPreview(systemId, true);

  if (runs.isLoading || preview.isLoading) {
    return (
      <Card className="p-5">
        <SkeletonText lines={5} />
      </Card>
    );
  }
  if (preview.error && !approved) return <>{fallback}</>;
  if (preview.error) {
    return (
      <ErrorState
        title="Could not load the obligations preview"
        error={preview.error}
        onRetry={() => preview.refetch()}
      />
    );
  }
  if (!preview.data || preview.data.classified === false) return <>{fallback}</>;
  const entries = previewEntries(preview.data.items ?? []);
  const applicable = entries.filter((e) => e.applicable !== false);
  const declared = String(preview.data.query?.risk_class ?? '');
  const risk = riskLabel(
    approved?.result?.risk_class ?? (declared && !declared.endsWith('_risk') ? `${declared}_risk` : declared),
  );
  const kb = preview.data.kb_version ?? approved?.kbVersion;

  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold">
          {approved
            ? 'Obligations that follow from the approved classification'
            : 'Obligations that follow from the system card'}
        </h2>
        <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
          Preview, no audit yet ·<Badge tone={risk.tone}>{risk.label}</Badge>
          {approved?.status === 'stale' && <Badge tone="warning">Stale</Badge>}
          {approved ? (
            <span className="font-mono">{approved.id}</span>
          ) : (
            <span>declared class, not yet classified by the agent</span>
          )}
          {kb && <span className="num font-mono">· kb {kb}</span>}
        </p>
      </div>

      {preview.data.prohibited && (
        <div
          role="status"
          className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/[0.05] p-3.5 text-sm"
        >
          <Ban className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
          <span>
            <span className="font-medium">Prohibited practice.</span>{' '}
            <span className="text-muted">
              The system may not be placed on the market or used in the EU (Art. 5).
            </span>
          </span>
        </div>
      )}

      {entries.length === 0 ? (
        <Card className="p-2">
          <EmptyState
            icon={<ListChecks />}
            title="No obligations activated"
            description="Reg-memory activated no catalogue row for this classification at this knowledge-base version."
          />
        </Card>
      ) : (
        <Card className="divide-y divide-border overflow-hidden">
          <div className="flex items-center justify-between bg-surface-muted/50 px-4 py-2.5 text-xs text-muted">
            <span>
              <span className="num font-semibold text-text">{applicable.length}</span> of {entries.length}{' '}
              apply
            </span>
            <span className="hidden sm:inline">In force from</span>
          </div>
          <ul className="divide-y divide-border">
            {entries.map((e) => (
              <li
                key={e.id}
                className={cn(
                  'flex flex-col gap-1.5 px-4 py-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4',
                  e.applicable === false && 'text-muted',
                )}
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">{e.label}</span>
                    {e.applicable === false ? (
                      <Badge>Not applicable</Badge>
                    ) : (
                      <Badge tone="primary">Applies</Badge>
                    )}
                  </div>
                  {e.summary && <div className="text-xs text-muted">{e.summary}</div>}
                  {e.reason && <p className="mt-0.5 text-2xs text-muted">{e.reason}</p>}
                  <div className="font-mono text-2xs text-muted [overflow-wrap:anywhere]">{e.id}</div>
                </div>
                <span className="num shrink-0 whitespace-nowrap font-mono text-xs">
                  {e.in_force_date ?? '–'}
                  {e.in_force_now != null && (
                    <span
                      className={cn(
                        'ml-1.5 font-sans text-2xs',
                        e.in_force_now ? 'text-success' : 'text-muted',
                      )}
                    >
                      {e.in_force_now ? 'in force' : 'not yet'}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
