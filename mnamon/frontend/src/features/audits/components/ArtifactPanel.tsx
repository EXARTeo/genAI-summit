import { AnimatePresence, motion } from 'framer-motion';
import { Hand } from 'lucide-react';
import type { ReactNode } from 'react';
import { formatRelative } from '@/shared/lib/format';
import { fadeIn } from '@/shared/lib/motion';
import { AgentThinking, Button, CodeBlock, EmptyState, StatusPill, Tabs } from '@/shared/ui';
import { STAGES, artifactsForStage, formatDuration, type StageDef, type StepState } from '../lib/pipeline';
import {
  findingsFromArtifacts,
  reportsFromArtifacts,
  toContext,
  toCritic,
  toDataset,
  toDatasetAnalysis,
  toFindings,
  toGenerationSpec,
  toModelProfile,
  toPublicCandidates,
  toScenarioAnalysis,
  toScenarios,
  toTestResults,
} from '../lib/adapters';
import type { Artifact } from '../lib/types';
import { TraceLink } from './artifact_parts/common';
import { CriticView, FindingsView, ReportView } from './artifact_parts/FindingViews';
import { ModelProfileView } from './artifact_parts/ModelProfileView';
import {
  ContextView,
  PublicCandidatesView,
  ScenarioAnalysisView,
  ScenariosView,
  TestResultsView,
} from './artifact_parts/PlanViews';
import { DatasetAnalysisView, DatasetView, GenerationSpecView } from './artifact_parts/SpecViews';
import { actorLabel } from '@/shared/lib/labels';

const TITLES: Record<string, string> = {
  context: 'Context',
  model_profile: 'Model profile',
  public_dataset_candidates: 'Public dataset candidates',
  scenarios: 'Scenarios',
  scenario_analysis: 'Scenario analysis',
  generation_spec: 'Generation spec',
  dataset: 'Dataset',
  dataset_analysis: 'Dataset analysis',
  test_plan: 'Test plan',
  test_result: 'Test results',
  finding: 'Findings',
  critic: 'Critic',
  report: 'Report',
};

/** Renders one artifact by kind through its adapter; unknown kinds fall back to JSON. */
export function ArtifactBody({ a }: { a: Artifact }) {
  const d: unknown = a.data;
  switch (a.kind) {
    case 'context':
      return <ContextView data={toContext(d)} />;
    case 'model_profile':
      return <ModelProfileView data={toModelProfile(d)} />;
    case 'public_dataset_candidates':
      return <PublicCandidatesView data={toPublicCandidates(d)} />;
    case 'scenarios':
      return <ScenariosView data={toScenarios(d)} />;
    case 'scenario_analysis':
      return <ScenarioAnalysisView data={toScenarioAnalysis(d)} />;
    case 'generation_spec':
      return <GenerationSpecView data={toGenerationSpec(d)} />;
    case 'dataset':
      return <DatasetView data={toDataset(d)} />;
    case 'dataset_analysis':
      return <DatasetAnalysisView data={toDatasetAnalysis(d)} />;
    case 'test_result':
      return <TestResultsView data={toTestResults(d)} />;
    case 'finding':
      return <FindingsView data={toFindings(d)} />;
    case 'critic':
      return <CriticView data={toCritic(d)} />;
    case 'report':
      return (
        <div className="space-y-8">
          {reportsFromArtifacts([a]).map((r) => (
            <ReportView key={r.key} data={r.report} />
          ))}
        </div>
      );
    default:
      return <CodeBlock code={JSON.stringify(a.data, null, 2)} language="json" maxHeight="28rem" />;
  }
}

function ArtifactHeader({ a }: { a: Artifact }) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
      <span className="font-medium text-text">
        {TITLES[a.kind] ?? a.kind}
        {a.name !== 'main' && <span className="text-muted"> · {a.name}</span>}
      </span>
      <span className="num font-mono">v{a.version}</span>
      <StatusPill status={a.status} />
      <span className="ml-auto truncate">
        {actorLabel(a.createdBy)} · {formatRelative(a.updatedAt)}
      </span>
    </div>
  );
}

function StepHeader({
  stage,
  state,
  index,
  duration,
  traceId,
}: {
  stage: StageDef;
  state: StepState;
  index: number;
  duration?: number;
  traceId?: string;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-start gap-x-4 gap-y-2 border-b border-border pb-4">
      <div className="min-w-0 flex-1">
        <div className="num text-2xs font-medium text-muted">
          Step {index + 1} of {STAGES.length}
          {stage.gate && ' · Human gate'}
        </div>
        <h2 className="mt-0.5 text-lg font-semibold tracking-tight">{stage.label}</h2>
        <p className="text-sm text-muted">{stage.description}</p>
      </div>
      <div className="flex items-center gap-3 pt-1 text-xs text-muted">
        {state === 'done' && duration != null && <span className="num">{formatDuration(duration)}</span>}
        {state !== 'pending' && <TraceLink traceId={traceId} label="Trace" />}
      </div>
    </div>
  );
}

export interface ArtifactPanelProps {
  stage: StageDef;
  state: StepState;
  artifacts: Artifact[];
  traceId?: string;
  /** Seconds the step took. */
  duration?: number;
  /** Position in STAGES. */
  index?: number;
  onReview?: () => void;
  /** Step facts shown under the step header (status, memory, redo history, decisions). */
  facts?: ReactNode;
}

export function ArtifactPanel({
  stage,
  state,
  artifacts,
  traceId,
  duration,
  index = 0,
  onReview,
  facts,
}: ArtifactPanelProps) {
  const list = artifactsForStage(stage, artifacts);
  const reports = stage.id === 'report' ? reportsFromArtifacts(list) : [];
  const findingArts = list.filter((a) => a.kind === 'finding');
  let body: ReactNode;

  if (stage.gate && state === 'needs-approval') {
    body = (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-warning/40 bg-warning/[0.06] p-4">
          <span className="approval-pulse grid size-8 place-items-center rounded-full bg-warning text-warning-foreground">
            <Hand className="size-4" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold">The agent is waiting for your decision</div>
            <div className="text-sm text-muted">
              Nothing runs past this gate until a person approves. The artifacts under review are below.
            </div>
          </div>
          <Button variant="warning" onClick={onReview}>
            Review & decide
          </Button>
        </div>
        {list.map((a) => (
          <div key={a.id} className="rounded-lg border border-border p-4">
            <ArtifactHeader a={a} />
            <ArtifactBody a={a} />
          </div>
        ))}
      </div>
    );
  } else if (list.length === 0) {
    body =
      state === 'active' ? (
        <div className="space-y-4 py-2">
          <AgentThinking label={`${stage.label}…`} detail={stage.description} />
          <div className="space-y-2.5 pt-2" aria-hidden>
            <div className="skeleton h-3 w-3/4" />
            <div className="skeleton h-3 w-1/2" />
            <div className="skeleton h-40 w-full" />
          </div>
        </div>
      ) : (
        <EmptyState
          compact
          title={state === 'pending' ? 'Not started yet' : stage.gate ? 'Gate passed' : 'No artifact'}
          description={stage.gate ? 'See the approvals recorded for this audit.' : stage.description}
        />
      );
  } else if (stage.id === 'report' && reports.length > 1) {
    body = (
      <Tabs defaultValue={reports[0].key}>
        <Tabs.List>
          {reports.map((r) => (
            <Tabs.Trigger key={r.key} value={r.key}>
              {r.report.audience === 'management' ? 'Management' : 'Engineer'}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        {reports.map((r) => (
          <Tabs.Content key={r.key} value={r.key}>
            <ArtifactHeader a={r.artifact} />
            <ReportView data={r.report} />
          </Tabs.Content>
        ))}
      </Tabs>
    );
  } else if (findingArts.length > 1) {
    const rest = list.filter((a) => a.kind !== 'finding');
    body = (
      <div className="space-y-8">
        <div>
          <div className="mb-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
            <span className="font-medium text-text">Findings</span>
            <span className="num">{findingArts.length} artifacts</span>
          </div>
          <FindingsView data={{ findings: findingsFromArtifacts(findingArts) }} />
        </div>
        {rest.map((a) => (
          <div key={a.id}>
            <ArtifactHeader a={a} />
            <ArtifactBody a={a} />
          </div>
        ))}
      </div>
    );
  } else {
    body = (
      <div className="space-y-8">
        {list.map((a) => (
          <div key={a.id}>
            <ArtifactHeader a={a} />
            <ArtifactBody a={a} />
          </div>
        ))}
      </div>
    );
  }

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={`${stage.id}-${state}-${list.length}`}
        variants={fadeIn}
        initial="initial"
        animate="animate"
        exit="exit"
      >
        <StepHeader stage={stage} state={state} index={index} duration={duration} traceId={traceId} />
        {facts}
        {body}
      </motion.div>
    </AnimatePresence>
  );
}
