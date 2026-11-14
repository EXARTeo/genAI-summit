import { AnimatePresence, motion } from 'framer-motion';
import { Hand } from 'lucide-react';
import type { ReactNode } from 'react';
import { formatRelative } from '@/shared/lib/format';
import { fadeIn } from '@/shared/lib/motion';
import { AgentThinking, Button, CodeBlock, EmptyState, StatusPill, Tabs } from '@/shared/ui';
import { STAGES, artifactsForStage, formatDuration, type StageDef, type StepState } from '../lib/pipeline';
import type {
  Artifact,
  ContextData,
  CriticData,
  DatasetAnalysisData,
  FindingsData,
  GenerationSpecData,
  ModelProfileData,
  ReportData,
  ScenarioAnalysisData,
  ScenariosData,
} from '../lib/types';
import { TraceLink } from './artifact_parts/common';
import { CriticView, FindingsView, ReportView } from './artifact_parts/FindingViews';
import { ModelProfileView } from './artifact_parts/ModelProfileView';
import { ContextView, ScenarioAnalysisView, ScenariosView } from './artifact_parts/PlanViews';
import { DatasetAnalysisView, GenerationSpecView } from './artifact_parts/SpecViews';

const TITLES: Record<string, string> = {
  context: 'Context',
  model_profile: 'Model profile',
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

/** Renders one artifact by kind; unknown kinds fall back to JSON. */
export function ArtifactBody({ a }: { a: Artifact }) {
  const d = a.data as unknown;
  switch (a.kind) {
    case 'context':
      return <ContextView data={d as ContextData} />;
    case 'model_profile':
      return <ModelProfileView data={d as ModelProfileData} />;
    case 'scenarios':
      return <ScenariosView data={d as ScenariosData} />;
    case 'scenario_analysis':
      return <ScenarioAnalysisView data={d as ScenarioAnalysisData} />;
    case 'generation_spec':
      return <GenerationSpecView data={d as GenerationSpecData} />;
    case 'dataset_analysis':
      return <DatasetAnalysisView data={d as DatasetAnalysisData} />;
    case 'finding':
      return <FindingsView data={d as FindingsData} />;
    case 'critic':
      return <CriticView data={d as CriticData} />;
    case 'report':
      return <ReportView data={d as ReportData} />;
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
      <span className="ml-auto">
        {a.createdBy} · {formatRelative(a.updatedAt)}
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
        {state === 'done' && duration != null && (
          <span className="num font-mono">{formatDuration(duration)}</span>
        )}
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
}

export function ArtifactPanel({
  stage,
  state,
  artifacts,
  traceId,
  duration,
  index = 0,
  onReview,
}: ArtifactPanelProps) {
  const list = artifactsForStage(stage, artifacts);
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
  } else if (stage.id === 'report' && list.length > 1) {
    body = (
      <Tabs defaultValue={list[0].name}>
        <Tabs.List>
          {list.map((a) => (
            <Tabs.Trigger key={a.id} value={a.name}>
              {a.name === 'management' ? 'Management' : a.name === 'engineer' ? 'Engineer' : a.name}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        {list.map((a) => (
          <Tabs.Content key={a.id} value={a.name}>
            <ArtifactHeader a={a} />
            <ArtifactBody a={a} />
          </Tabs.Content>
        ))}
      </Tabs>
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
        {body}
      </motion.div>
    </AnimatePresence>
  );
}
