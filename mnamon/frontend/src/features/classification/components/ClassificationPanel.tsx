import { AlertTriangle, Check, ChevronDown, History, RefreshCw, Scale, Sparkles, X } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { formatDateTime, formatRelative } from '@/shared/lib/format';
import { cn } from '@/shared/lib/utils';
import {
  Badge,
  Button,
  CardContent,
  CardFooter,
  CardHeader,
  ErrorState,
  GlowCard,
  Skeleton,
  StatusPill,
  toast,
} from '@/shared/ui';
import {
  useClassifications,
  useDecideClassification,
  useStartClassification,
} from '../hooks/useClassifications';
import {
  confidenceTone,
  inForce,
  latestRun,
  pct,
  previousFor,
  rejectReason,
  riskLabel,
  routeLabel,
  staleReason,
} from '../lib/classification';
import type { Classification, ClassificationResult } from '../lib/types';
import { DecisionDialog } from './parts/DecisionDialog';
import { HistorySheet } from './parts/HistorySheet';
import { IrisLine, ResultDetails } from './parts/ResultDetails';
import { RunProgress } from './parts/RunProgress';

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0 bg-surface px-4 py-3">
      <dt className="text-2xs font-medium uppercase tracking-wider text-muted">{label}</dt>
      <dd className="mt-1 flex min-h-6 min-w-0 flex-wrap items-center gap-1.5 text-sm">{children}</dd>
    </div>
  );
}

/** Class, route and the four facts a reviewer reads first. */
function Summary({ c, r, actions }: { c: Classification; r: ClassificationResult; actions?: ReactNode }) {
  const risk = riskLabel(r.risk_class);
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-lg font-semibold tracking-tight">{risk.label}</span>
            <StatusPill status={c.status} />
          </div>
          <p className="mt-0.5 text-sm text-muted">{routeLabel(r.route, r.art6_3?.condition)}</p>
        </div>
        {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
      </div>
      <dl className="grid grid-cols-1 gap-px border-t border-border bg-border sm:grid-cols-2 xl:grid-cols-4">
        <Fact label="Legal basis">
          <span className="font-mono text-xs [overflow-wrap:anywhere]">{r.annex_basis ?? '—'}</span>
        </Fact>
        <Fact label="AI Act role">
          <span className="capitalize">{r.role}</span>
        </Fact>
        <Fact label="Confidence">
          <Badge tone={confidenceTone(r.confidence)} className="num">
            {pct(r.confidence)}
          </Badge>
          <span className="text-xs text-muted">classifier</span>
        </Fact>
        <Fact label="Independent check (Iris)">
          <IrisLine r={r} />
        </Fact>
      </dl>
    </div>
  );
}

function Banner({
  tone,
  icon,
  title,
  children,
  action,
}: {
  tone: 'warning' | 'danger' | 'info';
  icon: ReactNode;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div
      role="status"
      className={cn(
        'flex flex-col gap-3 rounded-lg border p-3.5 text-sm sm:flex-row sm:items-start',
        tone === 'warning' && 'border-warning/30 bg-warning/[0.06]',
        tone === 'danger' && 'border-danger/30 bg-danger/[0.05]',
        tone === 'info' && 'border-border bg-surface-muted/50',
      )}
    >
      <span
        className={cn(
          'mt-0.5 shrink-0 [&_svg]:size-4',
          tone === 'warning' && 'text-warning',
          tone === 'danger' && 'text-danger',
          tone === 'info' && 'text-muted',
        )}
        aria-hidden
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="font-medium">{title}</div>
        {children && <div className="mt-1 text-muted">{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

function NeedsHuman({ r }: { r: ClassificationResult }) {
  if (!r.needs_human && !r.verifier_problems.length) return null;
  return (
    <Banner tone="warning" icon={<AlertTriangle />} title="Needs a careful human review">
      <ul className="list-disc space-y-0.5 pl-4">
        {r.needs_human_reasons.map((x, i) => (
          <li key={`n${i}`}>{x}</li>
        ))}
        {r.verifier_problems.map((x, i) => (
          <li key={`v${i}`}>Verifier: {x}</li>
        ))}
        {!r.needs_human_reasons.length && !r.verifier_problems.length && (
          <li>Low confidence or the judges disagree.</li>
        )}
      </ul>
    </Banner>
  );
}

/** "In force: High risk, approved 2 days ago" when the latest run is not the class in force. */
function InForceLine({ c }: { c: Classification | undefined }) {
  if (!c?.result) return null;
  const risk = riskLabel(c.result.risk_class);
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
      In force until a new one is approved:
      <Badge tone={risk.tone}>{risk.label}</Badge>
      <span className="font-mono">{c.id}</span>
      {c.status === 'stale' && <StatusPill status="stale" />}
    </p>
  );
}

/**
 * The Overview's risk-classification card (plan 02 §5): classify, follow the run, read the
 * proposal, approve or reject it, and see when a regulation change made it stale.
 */
export function ClassificationPanel({ systemId }: { systemId: string }) {
  const { data, isLoading, error, refetch } = useClassifications(systemId);
  const start = useStartClassification(systemId);
  const decide = useDecideClassification(systemId);
  const [dialog, setDialog] = useState<'approve' | 'reject' | null>(null);
  const [history, setHistory] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const runs = data ?? [];
  const last = latestRun(runs);
  const current = inForce(runs);
  const r = last?.result ?? null;

  const classify = (previousId?: string) =>
    start.mutate(previousId, {
      onSuccess: () => {
        setExpanded(false);
        toast.success('Classification started');
      },
      onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not start the classification'),
    });
  const reclassify = (label = 'Re-classify') => (
    <Button
      variant="secondary"
      size="sm"
      leftIcon={<RefreshCw />}
      loading={start.isPending}
      onClick={() => classify(previousFor(runs))}
    >
      {label}
    </Button>
  );

  let description = 'Proposed by an agent from the dossier and the regulation; a human approves.';
  if (last?.status === 'running') description = `Started ${formatRelative(last.createdAt)}`;
  else if (last?.status === 'proposed') description = 'A proposal is waiting for the AI Officer.';
  else if (current?.status === 'approved' && last === current)
    description = `Approved ${formatRelative(current.updatedAt)}`;

  let body: ReactNode;
  if (isLoading) {
    body = <Skeleton className="h-24 rounded-lg" />;
  } else if (error) {
    body = (
      <ErrorState compact title="Could not load classifications" error={error} onRetry={() => refetch()} />
    );
  } else if (!last) {
    body = (
      <div className="flex flex-col items-start gap-4 rounded-lg border border-dashed border-border p-5 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">Not classified yet</div>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            The agent screens Art. 5, Annex I and III, the Art. 6(3) derogation, Art. 50 and the provider or
            deployer role, cites the law at the pinned knowledge-base version, and an independent judge checks
            the class. Usually under a minute.
          </p>
        </div>
        <Button leftIcon={<Sparkles />} loading={start.isPending} onClick={() => classify()}>
          Classify risk
        </Button>
      </div>
    );
  } else if (last.status === 'running') {
    body = <RunProgress startedAt={last.createdAt} />;
  } else if (last.status === 'failed' || !r) {
    body = (
      <div className="space-y-3">
        <Banner
          tone="danger"
          icon={<AlertTriangle />}
          title="The classification failed"
          action={reclassify('Retry')}
        >
          {last.error ?? 'No result came back.'}
        </Banner>
        <InForceLine c={current} />
      </div>
    );
  } else if (last.status === 'proposed') {
    body = (
      <div className="space-y-4">
        <Summary
          c={last}
          r={r}
          actions={
            <>
              <Button variant="outline" size="sm" leftIcon={<X />} onClick={() => setDialog('reject')}>
                Reject
              </Button>
              <Button size="sm" leftIcon={<Check />} onClick={() => setDialog('approve')}>
                Approve
              </Button>
            </>
          }
        />
        <NeedsHuman r={r} />
        {current && current !== last && <InForceLine c={current} />}
        <ResultDetails r={r} />
      </div>
    );
  } else {
    // approved, stale, rejected or superseded: the summary, the reason, and the full proposal on demand.
    const stale = last.status === 'stale' ? staleReason(last) : null;
    const rejected = last.status === 'rejected' ? rejectReason(last) : null;
    body = (
      <div className="space-y-4">
        {stale && (
          <Banner
            tone="warning"
            icon={<AlertTriangle />}
            title="Stale: a regulation change touched a provision this class relies on"
            action={reclassify()}
          >
            {stale}. The approved class stays in force until a new one is approved.
          </Banner>
        )}
        {last.status === 'rejected' && (
          <Banner
            tone="info"
            icon={<X />}
            title="Rejected"
            action={reclassify('Re-classify with this feedback')}
          >
            {rejected ? `“${rejected}”` : 'No reason recorded.'} The next run reads the reason.
          </Banner>
        )}
        <Summary c={last} r={r} actions={last.status === 'approved' ? reclassify() : undefined} />
        {last.status === 'rejected' && current && <InForceLine c={current} />}
        <div>
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={expanded}
            onClick={() => setExpanded((v) => !v)}
            rightIcon={<ChevronDown className={cn('transition-transform', expanded && 'rotate-180')} />}
          >
            {expanded ? 'Hide the full proposal' : 'Show the full proposal'}
          </Button>
          {expanded && (
            <div className="mt-3">
              <ResultDetails r={r} />
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <GlowCard active={last?.status === 'running'}>
      <CardHeader
        icon={<Scale />}
        title="Risk classification"
        description={description}
        actions={
          runs.length > 0 && (
            <Button variant="ghost" size="sm" leftIcon={<History />} onClick={() => setHistory(true)}>
              History
              <span className="num text-muted">({runs.length})</span>
            </Button>
          )
        }
      />
      <CardContent>{body}</CardContent>
      {r && last && (
        <CardFooter className="flex-wrap gap-x-3 gap-y-1">
          <span>Proposal by an agent, not legal advice.</span>
          <span className="font-mono">{last.id}</span>
          {(last.kbVersion ?? r.kb_version) && (
            <span className="num font-mono">kb {last.kbVersion ?? r.kb_version}</span>
          )}
          {(last.traceId ?? r.trace_id) && (
            <span className="font-mono" title="Langfuse trace">
              trace {(last.traceId ?? r.trace_id)!.slice(0, 12)}
            </span>
          )}
          <time className="ml-auto" dateTime={last.createdAt} title={formatDateTime(last.createdAt)}>
            {formatRelative(last.createdAt)}
          </time>
        </CardFooter>
      )}

      {last && r && dialog && (
        <DecisionDialog
          open
          onOpenChange={(o) => !o && setDialog(null)}
          mode={dialog}
          classificationId={last.id}
          result={r}
          onSubmit={(reason) =>
            decide.mutateAsync({ id: last.id, decision: dialog, reason: reason || undefined })
          }
        />
      )}
      <HistorySheet open={history} onOpenChange={setHistory} runs={runs} />
    </GlowCard>
  );
}
