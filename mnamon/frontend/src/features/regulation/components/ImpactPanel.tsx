import { AlertTriangle, ChevronRight, History, RotateCcw } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { TONE_CLASSES } from '@/features/audits/lib/styling';
import { cn } from '@/shared/lib/utils';
import { AgentThinking, Badge, Select, toast } from '@/shared/ui';
import { useOverrideJudge } from '../hooks/useRegulation';
import { JUDGE, effectiveDecision, worstDecision } from '../lib/regulation';
import type { AffectedSystem, JudgeDecision, RegChange } from '../lib/types';

/** The change judge's verdict per affected system: one compact row each, reasoning on demand. */
export function ImpactPanel({ c }: { c: RegChange }) {
  const worst = worstDecision(c);
  return (
    <section aria-label="Impact on systems" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Impact on systems</h3>
        {c.affected.length > 0 && (
          <span className="inline-flex items-center gap-1.5 text-2xs text-muted">
            <span className={cn('size-1.5 rounded-full', TONE_CLASSES[JUDGE[worst].tone].bg)} />
            worst: {JUDGE[worst].label}
          </span>
        )}
      </div>
      {c.judge === 'running' && (
        <div className="rounded-md border border-primary/25 bg-primary/5 px-3 py-2">
          <AgentThinking size="sm" label="Change judge: impact index, then Oumi Iris per affected system" />
        </div>
      )}
      {c.judge === 'failed' && (
        <div className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
          <AlertTriangle className="size-3.5 shrink-0" />
          The change judge failed. The change stays accepted; check the trace and run it again.
        </div>
      )}
      {c.affected.length > 0 ? (
        <div className="overflow-hidden rounded-md border border-border">
          {c.affected.map((a) => (
            <ImpactRow key={a.systemId} c={c} a={a} />
          ))}
        </div>
      ) : (
        c.judge !== 'running' && (
          <p className="text-xs text-muted">
            {c.status === 'proposed'
              ? 'Accept the change to run the impact index and the change judge.'
              : c.judge === 'done'
                ? 'No system affected: the impact index found no linked obligation.'
                : 'No judgement yet.'}
          </p>
        )
      )}
    </section>
  );
}

function ImpactRow({ c, a }: { c: RegChange; a: AffectedSystem }) {
  const [open, setOpen] = useState(false);
  const override = useOverrideJudge();
  const eff = effectiveDecision(a);
  const tone = TONE_CLASSES[JUDGE[eff].tone];
  const stale = a.staleFindings?.length ?? 0;
  return (
    <div className="border-b border-border text-xs last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex min-w-0 items-center gap-2 text-left"
        >
          <ChevronRight
            className={cn('size-3.5 shrink-0 text-muted transition-transform', open && 'rotate-90')}
          />
          <span className={cn('size-2 shrink-0 rounded-full', tone.bg)} />
          <span className="font-mono text-2xs text-muted">{a.systemId}</span>
          <span className="truncate font-medium">{a.systemName}</span>
        </button>
        <span className={cn('font-medium', tone.text)}>{JUDGE[eff].label}</span>
        <span className="tabular-nums text-muted">{Math.round(a.confidence * 100)}%</span>
        {stale > 0 && (
          <Badge tone="warning" icon={<History />}>
            {stale} stale
          </Badge>
        )}
        <span className="ml-auto flex items-center gap-3">
          {a.rerunAuditId && (
            <Link
              to={`/audits/${encodeURIComponent(a.rerunAuditId)}`}
              className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
            >
              <RotateCcw className="size-3" /> Re-run {a.rerunAuditId}
            </Link>
          )}
        </span>
      </div>
      {open && (
        <div className="space-y-2 border-t border-border/60 bg-surface-sunken/40 px-3 py-2.5 pl-9">
          <p className="max-w-prose text-sm leading-relaxed [overflow-wrap:anywhere]">{a.reasoning}</p>
          {a.counterArgument && (
            <p className="max-w-prose text-muted [overflow-wrap:anywhere]">
              <span className="font-medium text-text/80">Strongest counter-argument:</span>{' '}
              {a.counterArgument}
            </p>
          )}
          {a.path.length > 0 && (
            <p className="font-mono text-2xs text-muted [overflow-wrap:anywhere]">{a.path.join('  →  ')}</p>
          )}
          {(a.obligations?.length ?? 0) > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="mr-1 text-2xs text-muted">Obligations touched</span>
              {a.obligations!.map((o) => (
                <Badge key={o} className="font-mono">
                  {o}
                </Badge>
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3 pt-1">
            <Select
              className="h-7 w-52 text-xs"
              aria-label="Override the change judge"
              value={eff}
              onValueChange={(v) =>
                override.mutate(
                  { id: c.id, systemId: a.systemId, decision: v as JudgeDecision },
                  {
                    onSuccess: () =>
                      toast.success(`${a.systemId}: ${JUDGE[v as JudgeDecision].label}`, {
                        description: 'Override logged; it can become memory.',
                      }),
                  },
                )
              }
              options={(Object.keys(JUDGE) as JudgeDecision[]).map((d) => ({
                value: d,
                label: JUDGE[d].label,
              }))}
            />
            {a.humanDecision && a.humanDecision !== a.decision && (
              <span className="text-muted">judge said {JUDGE[a.decision].label}, overridden</span>
            )}
            {a.auditId && (
              <Link
                to={`/audits/${encodeURIComponent(a.auditId)}?view=findings`}
                className="text-muted hover:text-text hover:underline"
              >
                findings read: {a.auditId}
              </Link>
            )}
            {a.rerunAuditId && (
              <Link
                to={`/audits/${encodeURIComponent(a.rerunAuditId)}?view=findings`}
                className="text-muted hover:text-text hover:underline"
              >
                delta report
              </Link>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
