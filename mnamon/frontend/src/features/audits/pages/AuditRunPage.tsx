import { ChevronRight, FileText, Hand, ListChecks, Play, RotateCw, Square, Workflow } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { ChatAboutButton } from '@/features/chat/components/ChatAboutButton';
import { ApprovalDrawer } from '@/features/approvals/components/ApprovalDrawer';
import { useMediaQuery } from '@/shared/hooks/useMediaQuery';
import { useUiStore } from '@/shared/stores/ui';
import { cn } from '@/shared/lib/utils';
import {
  AnimatedNumber,
  Button,
  Card,
  ErrorState,
  PageHeader,
  Sheet,
  Skeleton,
  StatusPill,
  Tabs,
  toast,
} from '@/shared/ui';
import { ArtifactPanel } from '../components/ArtifactPanel';
import { AuditPins } from '../components/AuditPins';
import { FindingsPanel } from '../components/FindingsPanel';
import { ReportPanel } from '../components/ReportPanel';
import { AuditPipeline } from '../components/AuditPipeline';
import { PipelineFlow } from '../components/PipelineFlow';
import { StepFacts } from '../components/StepFacts';
import { PipelineHeader, RunStatusCard, type RunChip } from '../components/pipeline_parts/PipelineHeader';
import { TraceLink } from '../components/artifact_parts/common';
import { useAudit, useRetryAudit } from '../hooks/useAudits';
import { useElementHeight } from '../hooks/useElementHeight';
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
import { auditLabel } from '@/shared/lib/labels';

type AuditView = 'pipeline' | 'findings' | 'report';
const VIEWS: { id: AuditView; label: string; icon: typeof Workflow }[] = [
  { id: 'pipeline', label: 'Pipeline', icon: Workflow },
  { id: 'findings', label: 'Findings', icon: ListChecks },
  { id: 'report', label: 'Report', icon: FileText },
];

/** Pipeline | Findings | Report (`?view=`). */
function ViewTabs({ view, onChange }: { view: AuditView; onChange: (v: AuditView) => void }) {
  return (
    <Tabs value={view} onValueChange={(v) => onChange(v as AuditView)}>
      <Tabs.List aria-label="Audit view" className="pg-float h-9 rounded-xl p-1">
        {VIEWS.map(({ id, label, icon: Icon }) => (
          <Tabs.Trigger key={id} value={id} className="h-7 rounded-lg">
            <Icon /> {label}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
    </Tabs>
  );
}

/** The step panel's width (42rem); the graph keeps the selected node clear of it. */
const PANEL_PX = 672;

const STATE_PILL = {
  done: 'done',
  active: 'running',
  pending: 'pending',
  blocked: 'failed',
  'needs-approval': 'awaiting_approval',
} as const;

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

/** The hero page: on wide screens the whole page is the pipeline graph (title and controls float on it, a step opens in a side panel); phones get the step list with the step below it. */
export function AuditRunPage() {
  const { auditId } = useParams();
  const { data, isLoading, error, refetch } = useAudit(auditId);
  const { view: audit, replaying, start, stop } = useReplay(data);
  // `?step=<stage id>` deep-links (and pins) a step; otherwise the page follows the live step.
  const [params, setParams] = useSearchParams();
  const pinned = params.get('step');
  const viewParam = params.get('view');
  const view: AuditView = viewParam === 'findings' || viewParam === 'report' ? viewParam : 'pipeline';
  const retry = useRetryAudit(auditId ?? '');
  const [selected, setSelected] = useState<string | null>(pinned);
  const [follow, setFollow] = useState(!pinned);
  const [drawer, setDrawer] = useState(false);
  // Wide screens: the picked step opens in a side panel beside the graph (a deep link opens it too).
  const [panel, setPanel] = useState(!!pinned);
  const overlay = useElementHeight<HTMLElement>();
  const setFullBleed = useUiStore((s) => s.setFullBleed);

  // Follow the live step until the user picks one.
  const live = audit ? defaultSelectedStage(audit) : null;
  useEffect(() => {
    if (follow && live) setSelected(live);
  }, [follow, live]);

  // Wide screens get the pipeline graph; phones keep the vertical step list.
  const wide = useMediaQuery('(min-width: 1024px)');
  // Wide + loaded: the page becomes a full-screen canvas (the shell drops its padding).
  const canvasPage = wide && !!audit && view === 'pipeline';
  useEffect(() => {
    setFullBleed(canvasPage);
    return () => setFullBleed(false);
  }, [canvasPage, setFullBleed]);
  const openReview = useCallback(() => setDrawer(true), []);
  const pick = useCallback(
    (id: string) => {
      setFollow(false);
      setSelected(id);
      setPanel(true);
      setParams(
        (p) => {
          p.set('step', id);
          return p;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const setView = useCallback(
    (v: AuditView) =>
      setParams(
        (p) => {
          if (v === 'pipeline') p.delete('view');
          else p.set('view', v);
          return p;
        },
        { replace: true },
      ),
    [setParams],
  );

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
  const chip: RunChip = replaying
    ? 'replay'
    : waiting
      ? 'waiting'
      : done
        ? 'done'
        : audit.status === 'failed'
          ? 'failed'
          : audit.status === 'running' || audit.status === 'open'
            ? 'live'
            : 'idle';
  const stepText = done
    ? `All ${STAGES.length} steps${elapsed > 0 ? ` · ${formatDuration(elapsed)}` : ''}`
    : `Step ${cur + 1} of ${STAGES.length}${elapsed > 0 ? ` · ${formatDuration(elapsed)}` : ''}`;

  const onFollow = () => {
    setFollow(true);
    setParams({}, { replace: true });
  };

  const titleText = (
    <>
      {audit.data.systemName ?? audit.systemId}
      <span className="font-normal text-muted"> · {audit.data.title ?? 'Audit'}</span>
    </>
  );
  const statusPill = (
    <StatusPill
      status={replaying ? 'running' : waiting ? 'needs_approval' : audit.status}
      label={replaying ? 'Replay' : statusLabel(audit.status)}
    />
  );
  const metaLine = (
    <span className="num flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs">
      <span>{audit.systemId}</span>
      {audit.data.trigger && audit.data.trigger !== 'manual' && (
        <span className="font-sans">Triggered by {audit.data.trigger}</span>
      )}
    </span>
  );
  const actions = (
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
      {data?.status === 'failed' && !replaying && (
        <Button
          variant="primary"
          leftIcon={<RotateCw />}
          loading={retry.isPending}
          onClick={() =>
            retry.mutate(undefined, {
              onSuccess: () => toast.success('Retrying: the pipeline re-runs the failed step'),
              onError: (e) => toast.error(e instanceof Error ? e.message : 'Retry failed'),
            })
          }
        >
          Retry
        </Button>
      )}
      {waiting && !replaying && (
        <Button variant="warning" leftIcon={<Hand />} onClick={() => setDrawer(true)}>
          Review & decide
        </Button>
      )}
    </>
  );
  const verdicts = (
    [
      ['indicates_gap', summary?.gaps],
      ['supports_compliance', summary?.supports],
      ['inconclusive', summary?.inconclusive],
      ['not_assessable_by_testing', summary?.notAssessable],
    ] as const
  ).map(([v, n]) => ({ v, n: n ?? 0, st: verdictStyle(v) }));
  const showSummary = done && !!summary && !replaying;
  const stepPanel = (
    <ArtifactPanel
      stage={stage}
      state={state}
      artifacts={audit.artifacts}
      traceId={audit.data.stageTraces?.[stage.id]}
      duration={audit.data.stageDurations?.[stage.id]}
      index={STAGES.indexOf(stage)}
      onReview={() => setDrawer(true)}
      facts={<StepFacts audit={audit} stage={stage} state={state} />}
      showHeader={!wide}
    />
  );
  const approvals = (
    <ApprovalDrawer auditId={audit.id} gate={gate} open={drawer && !replaying} onOpenChange={setDrawer} />
  );

  const pins = <AuditPins audit={audit} />;
  const tabs = <ViewTabs view={view} onChange={setView} />;

  if (view !== 'pipeline') {
    return (
      <div>
        <PageHeader
          breadcrumbs={[{ label: 'Audits', to: '/audits' }, { label: auditLabel(audit) }]}
          title={titleText}
          meta={statusPill}
          description={metaLine}
          actions={actions}
        />
        <div className="-mt-2 mb-4 space-y-3">
          {pins}
          {tabs}
        </div>
        {view === 'findings' ? <FindingsPanel audit={audit} /> : <ReportPanel audit={audit} />}
        {approvals}
      </div>
    );
  }

  if (wide) {
    // The page is the canvas: the graph fills the whole content area; title, actions, run
    // status, legend and zoom controls float on it (a soft fade under the title lets the graph
    // slide beneath it when panned).
    return (
      <div className="relative min-h-0 flex-1 overflow-hidden">
        <div className="absolute inset-0">
          <PipelineFlow
            audit={audit}
            selected={stage.id}
            onSelect={pick}
            onReview={openReview}
            coveredRight={panel ? PANEL_PX : 0}
            insetTop={overlay.height}
          />
        </div>
        <div
          className="pg-topfade pointer-events-none absolute inset-x-0 top-0"
          style={{ height: Math.max(overlay.height - 8, 0) }}
          aria-hidden
        />
        <header
          ref={overlay.ref}
          className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-start justify-between gap-6 px-8 pb-6 pt-6"
        >
          <div className="pointer-events-auto min-w-0">
            <nav aria-label="Breadcrumb" className="mb-2 flex items-center gap-1 text-xs text-muted">
              <Link to="/audits" className="transition-colors hover:text-text">
                Audits
              </Link>
              <ChevronRight className="size-3 opacity-60" />
              <span className="truncate text-text/80">{auditLabel(audit)}</span>
            </nav>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{titleText}</h1>
              {statusPill}
            </div>
            <div className="mt-1 text-muted">{metaLine}</div>
            <div className="mt-2">{pins}</div>
            <div className="mt-3">{tabs}</div>
            {showSummary && (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {verdicts.map(({ v, n, st }) => (
                  <span
                    key={v}
                    className="pg-float inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs"
                  >
                    <span className={cn('size-1.5 rounded-full', TONE_CLASSES[st.tone].dot)} />
                    <span
                      className={cn('num font-semibold', v === 'indicates_gap' && n > 0 && 'text-danger')}
                    >
                      {n}
                    </span>
                    <span className="text-muted">{st.label}</span>
                  </span>
                ))}
                <span className="pg-float num inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs">
                  <span className="font-semibold">{formatDuration(elapsed)}</span>
                  <span className="text-muted">agent time</span>
                </span>
              </div>
            )}
          </div>
          <div className="pointer-events-auto flex shrink-0 flex-col items-end gap-3">
            <div className="flex flex-wrap items-center justify-end gap-2">{actions}</div>
            <RunStatusCard
              chip={chip}
              stepText={stepText}
              progress={pct}
              follow={follow}
              onFollow={onFollow}
            />
          </div>
        </header>

        <Sheet
          open={panel}
          onOpenChange={setPanel}
          modal={false}
          keepOpenOn={(t) => !!t.closest('.react-flow__node-step, [role="dialog"]')}
          width="w-[min(42rem,100vw)]"
          title={
            <span className="flex items-center gap-2">
              {stage.label}
              <StatusPill status={STATE_PILL[state]} />
            </span>
          }
          description={stage.description}
        >
          {stepPanel}
        </Sheet>
        {approvals}
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: 'Audits', to: '/audits' }, { label: auditLabel(audit) }]}
        title={titleText}
        meta={statusPill}
        description={metaLine}
        actions={actions}
      />
      <div className="-mt-2 mb-4 space-y-3">
        {pins}
        {tabs}
      </div>

      {showSummary && (
        <Card className="mb-4 grid grid-cols-2 divide-border sm:grid-cols-5 sm:divide-x">
          {verdicts.map(({ v, n, st }) => (
            <div key={v} className="px-4 py-3">
              <div className="flex items-center gap-1.5 text-xs text-muted">
                <span className={cn('size-1.5 rounded-full', TONE_CLASSES[st.tone].dot)} />
                {st.label}
              </div>
              <AnimatedNumber
                value={n}
                className={cn(
                  'num mt-0.5 block text-2xl font-semibold',
                  v === 'indicates_gap' && n > 0 && 'text-danger',
                )}
              />
            </div>
          ))}
          <div className="col-span-2 border-t border-border px-4 py-3 sm:col-span-1 sm:border-t-0">
            <div className="text-xs text-muted">Agent time</div>
            <div className="num mt-0.5 text-2xl font-semibold">{formatDuration(elapsed)}</div>
          </div>
        </Card>
      )}

      <div className="grid items-start gap-4">
        <Card className="overflow-hidden">
          <PipelineHeader
            chip={chip}
            stepText={stepText}
            progress={pct}
            follow={follow}
            onFollow={onFollow}
          />
          <div className="px-3 pb-4">
            <AuditPipeline audit={audit} selected={stage.id} onSelect={pick} onReview={openReview} />
          </div>
        </Card>
        <Card
          className={cn(
            'min-w-0 p-5',
            state === 'active' && 'glow-border border-primary/30',
            state === 'needs-approval' && 'border-warning/40',
          )}
        >
          {stepPanel}
        </Card>
      </div>
      {approvals}
    </div>
  );
}
