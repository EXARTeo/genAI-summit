import { ClipboardCheck, Play, Square } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { ApprovalDrawer } from '@/features/approvals/components/ApprovalDrawer';
import {
  AnimatedNumber,
  Badge,
  Button,
  Card,
  ErrorState,
  GlowCard,
  PageHeader,
  ProgressRing,
  Skeleton,
  StatusPill,
} from '@/shared/ui';
import { ArtifactPanel } from '../components/ArtifactPanel';
import { AuditPipeline } from '../components/AuditPipeline';
import { TraceLink, VerdictPill } from '../components/artifact_parts/common';
import { useAudit } from '../hooks/useAudits';
import { useReplay } from '../hooks/useReplay';
import { STAGES, defaultSelectedStage, progress, statusLabel, stepState } from '../lib/pipeline';

/** The hero page: live pipeline on the left, the selected step's artifact on the right. */
export function AuditRunPage() {
  const { auditId } = useParams();
  const { data, isLoading, error, refetch } = useAudit(auditId);
  const { view: audit, replaying, start, stop } = useReplay(data);
  const [selected, setSelected] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [drawer, setDrawer] = useState(false);

  // Follow the live step until the user picks one.
  const live = audit ? defaultSelectedStage(audit) : null;
  useEffect(() => {
    if (follow && live) setSelected(live);
  }, [follow, live]);

  if (isLoading) return <Skeleton className="h-[70vh] w-full" />;
  if (error || !audit) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const stageId = selected ?? defaultSelectedStage(audit);
  const stage = STAGES.find((s) => s.id === stageId) ?? STAGES[0];
  const state = stepState(stage.id, audit);
  const gate = STAGES.find((s) => s.id === audit.stage)?.gate?.id ?? null;
  const summary = audit.data.summary;
  const waiting = audit.status === 'waiting_approval';

  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: 'Audits', to: '/audits' }, { label: audit.id }]}
        eyebrow={<span className="font-mono">{audit.id}</span>}
        title={`${audit.data.systemName ?? audit.systemId}: ${audit.data.title ?? 'Audit'}`}
        icon={<ClipboardCheck />}
        meta={
          <>
            <StatusPill
              status={replaying ? 'running' : waiting ? 'needs_approval' : audit.status}
              label={replaying ? 'Replay' : statusLabel(audit.status)}
            />
            {audit.data.kbVersion && <Badge className="font-mono">kb {audit.data.kbVersion}</Badge>}
            {audit.data.cardVersion != null && (
              <Badge className="font-mono">card v{audit.data.cardVersion}</Badge>
            )}
          </>
        }
        description={
          audit.data.trigger && audit.data.trigger !== 'manual'
            ? `Triggered by ${audit.data.trigger}`
            : undefined
        }
        actions={
          <div className="flex items-center gap-2">
            <TraceLink traceId={audit.data.traceId} label="Full trace" />
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
              <Button variant="warning" onClick={() => setDrawer(true)}>
                Review & decide
              </Button>
            )}
          </div>
        }
      />

      {audit.status === 'done' && summary && !replaying && (
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(
            [
              ['indicates_gap', summary.gaps],
              ['supports_compliance', summary.supports],
              ['inconclusive', summary.inconclusive],
              ['not_assessable_by_testing', summary.notAssessable],
            ] as const
          ).map(([v, n]) => (
            <Card key={v} className="flex items-center justify-between p-3">
              <VerdictPill verdict={v} />
              <AnimatedNumber value={n ?? 0} className="text-2xl font-semibold" />
            </Card>
          ))}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(300px,380px)_1fr]">
        <Card className="h-fit p-4 lg:sticky lg:top-4">
          <div className="mb-4 flex items-center gap-3">
            <ProgressRing
              value={progress(audit)}
              size={40}
              tone={audit.status === 'done' ? 'success' : waiting ? 'warning' : 'gradient'}
            />
            <div className="min-w-0 flex-1 text-sm">
              <div className="font-medium">Engineer pipeline</div>
              <div className="text-xs text-muted">
                {follow ? 'Following the live step' : 'Pinned to your selection'}
              </div>
            </div>
            {!follow && (
              <Button size="sm" variant="ghost" onClick={() => setFollow(true)}>
                Follow
              </Button>
            )}
          </div>
          <AuditPipeline
            audit={audit}
            selected={stage.id}
            onSelect={(id) => {
              setFollow(false);
              setSelected(id);
            }}
            onReview={() => setDrawer(true)}
          />
        </Card>
        <GlowCard active={state === 'active' || state === 'needs-approval'} className="min-w-0 p-5">
          <ArtifactPanel
            stage={stage}
            state={state}
            artifacts={audit.artifacts}
            traceId={audit.data.stageTraces?.[stage.id]}
            onReview={() => setDrawer(true)}
          />
        </GlowCard>
      </div>

      <ApprovalDrawer auditId={audit.id} gate={gate} open={drawer && !replaying} onOpenChange={setDrawer} />
    </div>
  );
}
