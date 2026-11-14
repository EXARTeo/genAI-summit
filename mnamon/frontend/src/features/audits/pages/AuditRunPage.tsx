import { Hand, Play, Square } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { ChatAboutButton } from '@/features/chat/components/ChatAboutButton';
import { ApprovalDrawer } from '@/features/approvals/components/ApprovalDrawer';
import { cn } from '@/shared/lib/utils';
import { AnimatedNumber, Button, Card, ErrorState, PageHeader, Skeleton, StatusPill } from '@/shared/ui';
import { ArtifactPanel } from '../components/ArtifactPanel';
import { AuditPipeline } from '../components/AuditPipeline';
import { TraceLink } from '../components/artifact_parts/common';
import { useAudit } from '../hooks/useAudits';
import { useReplay } from '../hooks/useReplay';
import { TONE_CLASSES, verdictStyle } from '../lib/styling';
import {
  STAGES,
  defaultSelectedStage,
  formatDuration,
  progress,
  stageIndex,
  statusLabel,
  stepState,
} from '../lib/pipeline';

function RunSkeleton() {
  return (
    <div className="space-y-6" aria-busy>
      <div className="space-y-2">
        <Skeleton className="h-3 w-40" />
        <Skeleton className="h-7 w-80" />
      </div>
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card className="space-y-3 p-4">
          {Array.from({ length: 9 }, (_, i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton className="size-5 rounded-full" />
              <Skeleton className="h-3 flex-1" />
            </div>
          ))}
        </Card>
        <Card className="space-y-4 p-5">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-56" />
          <Skeleton className="h-24" />
        </Card>
      </div>
    </div>
  );
}

/** The hero page: live pipeline on the left, the selected step's artifact on the right. */
export function AuditRunPage() {
  const { auditId } = useParams();
  const { data, isLoading, error, refetch } = useAudit(auditId);
  const { view: audit, replaying, start, stop } = useReplay(data);
  // `?step=<stage id>` deep-links (and pins) a step; otherwise the page follows the live step.
  const [params, setParams] = useSearchParams();
  const pinned = params.get('step');
  const [selected, setSelected] = useState<string | null>(pinned);
  const [follow, setFollow] = useState(!pinned);
  const [drawer, setDrawer] = useState(false);

  // Follow the live step until the user picks one.
  const live = audit ? defaultSelectedStage(audit) : null;
  useEffect(() => {
    if (follow && live) setSelected(live);
  }, [follow, live]);

  if (isLoading) return <RunSkeleton />;
  if (error || !audit) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const stageId = selected ?? defaultSelectedStage(audit);
  const stage = STAGES.find((s) => s.id === stageId) ?? STAGES[0];
  const state = stepState(stage.id, audit);
  const gate = STAGES.find((s) => s.id === audit.stage)?.gate?.id ?? null;
  const summary = audit.data.summary;
  const waiting = audit.status === 'waiting_approval';
  const done = audit.status === 'done';
  const cur = stageIndex(audit.stage);
  const elapsed = Object.values(audit.data.stageDurations ?? {}).reduce((a, b) => a + b, 0);
  const pct = progress(audit);

  const pick = (id: string) => {
    setFollow(false);
    setSelected(id);
    setParams(
      (p) => {
        p.set('step', id);
        return p;
      },
      { replace: true },
    );
  };

  return (
    <div>
      <PageHeader
        breadcrumbs={[
          { label: 'Audits', to: '/audits' },
          { label: <span className="font-mono">{audit.id}</span> },
        ]}
        title={
          <>
            {audit.data.systemName ?? audit.systemId}
            <span className="font-normal text-muted"> · {audit.data.title ?? 'Audit'}</span>
          </>
        }
        meta={
          <StatusPill
            status={replaying ? 'running' : waiting ? 'needs_approval' : audit.status}
            label={replaying ? 'Replay' : statusLabel(audit.status)}
          />
        }
        description={
          <span className="num flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs">
            <span>{audit.systemId}</span>
            {audit.data.kbVersion && <span>kb {audit.data.kbVersion}</span>}
            {audit.data.cardVersion != null && <span>card v{audit.data.cardVersion}</span>}
            {audit.data.trigger && audit.data.trigger !== 'manual' && (
              <span className="font-sans">Triggered by {audit.data.trigger}</span>
            )}
          </span>
        }
        actions={
          <>
            <TraceLink traceId={audit.data.traceId} label="Full trace" variant="button" />
            <ChatAboutButton systemId={audit.systemId} auditId={audit.id} label="Chat about this audit" />
            {data?.status === 'done' &&
              (replaying ? (
                <Button variant="secondary" leftIcon={<Square />} onClick={stop}>
                  Stop replay
                </Button>
              ) : (
                <Button
                  variant="secondary"
                  leftIcon={<Play />}
                  onClick={() => {
                    setFollow(true);
                    start();
                  }}
                >
                  Replay run
                </Button>
              ))}
            {waiting && !replaying && (
              <Button variant="warning" leftIcon={<Hand />} onClick={() => setDrawer(true)}>
                Review & decide
              </Button>
            )}
          </>
        }
      />

      {done && summary && !replaying && (
        <Card className="mb-4 grid grid-cols-2 divide-border sm:grid-cols-5 sm:divide-x">
          {(
            [
              ['indicates_gap', summary.gaps],
              ['supports_compliance', summary.supports],
              ['inconclusive', summary.inconclusive],
              ['not_assessable_by_testing', summary.notAssessable],
            ] as const
          ).map(([v, n]) => {
            const st = verdictStyle(v);
            return (
              <div key={v} className="px-4 py-3">
                <div className="flex items-center gap-1.5 text-xs text-muted">
                  <span className={cn('size-1.5 rounded-full', TONE_CLASSES[st.tone].dot)} />
                  {st.label}
                </div>
                <AnimatedNumber
                  value={n ?? 0}
                  className={cn(
                    'num mt-0.5 block text-2xl font-semibold',
                    v === 'indicates_gap' && (n ?? 0) > 0 && 'text-danger',
                  )}
                />
              </div>
            );
          })}
          <div className="col-span-2 border-t border-border px-4 py-3 sm:col-span-1 sm:border-t-0">
            <div className="text-xs text-muted">Agent time</div>
            <div className="num mt-0.5 text-2xl font-semibold">{formatDuration(elapsed)}</div>
          </div>
        </Card>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <Card className="overflow-hidden lg:sticky lg:top-[calc(var(--topbar-height)+1rem)]">
          <div className="border-b border-border px-4 py-3">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium">Pipeline</span>
              <span className="num text-muted">
                {done ? `${STAGES.length}/${STAGES.length} steps` : `Step ${cur + 1} of ${STAGES.length}`}
                {elapsed > 0 && ` · ${formatDuration(elapsed)}`}
              </span>
            </div>
            <div className="mt-2 h-1 overflow-hidden rounded-full bg-surface-muted">
              <div
                className={cn(
                  'h-full rounded-full transition-[width] duration-500 ease-out',
                  waiting ? 'bg-warning' : 'bg-primary',
                )}
                style={{ width: `${Math.round(pct * 100)}%` }}
              />
            </div>
            <div className="mt-2 flex items-center justify-between text-2xs text-muted">
              <span>{follow ? 'Following the live step' : 'Pinned to your selection'}</span>
              {!follow && (
                <button
                  type="button"
                  className="font-medium text-primary hover:underline"
                  onClick={() => {
                    setFollow(true);
                    setParams({}, { replace: true });
                  }}
                >
                  Follow live
                </button>
              )}
            </div>
          </div>
          <div className="p-1.5">
            <AuditPipeline
              audit={audit}
              selected={stage.id}
              onSelect={pick}
              onReview={() => setDrawer(true)}
            />
          </div>
        </Card>

        <Card
          className={cn(
            'min-w-0 p-5',
            state === 'active' && 'glow-border border-primary/30',
            state === 'needs-approval' && 'border-warning/40',
          )}
        >
          <ArtifactPanel
            stage={stage}
            state={state}
            artifacts={audit.artifacts}
            traceId={audit.data.stageTraces?.[stage.id]}
            duration={audit.data.stageDurations?.[stage.id]}
            index={STAGES.indexOf(stage)}
            onReview={() => setDrawer(true)}
          />
        </Card>
      </div>

      <ApprovalDrawer auditId={audit.id} gate={gate} open={drawer && !replaying} onOpenChange={setDrawer} />
    </div>
  );
}
