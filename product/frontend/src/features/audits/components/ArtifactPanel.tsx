import { AnimatePresence, motion } from 'framer-motion';
import { Hand } from 'lucide-react';
import type { ReactNode } from 'react';
import { formatRelative } from '@/shared/lib/format';
import { fadeIn } from '@/shared/lib/motion';
import { AgentThinking, Button, Card, CodeBlock, EmptyState, StatusPill, Tabs } from '@/shared/ui';
import { artifactsForStage, type StageDef, type StepState } from '../lib/pipeline';
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

function ArtifactHeader({ a, traceId }: { a: Artifact; traceId?: string }) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 border-b border-border pb-3">
      <h3 className="text-base font-semibold">
        {TITLES[a.kind] ?? a.kind}
        {a.name !== 'main' && <span className="text-muted"> · {a.name}</span>}
      </h3>
      <span className="font-mono text-xs text-muted">v{a.version}</span>
      <StatusPill status={a.status} />
      <span className="text-xs text-muted">
        {a.createdBy} · {formatRelative(a.updatedAt)}
      </span>
      <TraceLink traceId={traceId} className="ml-auto" />
    </div>
  );
}

export interface ArtifactPanelProps {
  stage: StageDef;
  state: StepState;
  artifacts: Artifact[];
  traceId?: string;
  onReview?: () => void;
}

export function ArtifactPanel({ stage, state, artifacts, traceId, onReview }: ArtifactPanelProps) {
  const list = artifactsForStage(stage, artifacts);
  let body: ReactNode;

  if (stage.gate && state === 'needs-approval') {
    body = (
      <div className="space-y-4">
        <div className="approval-pulse flex flex-wrap items-center gap-3 rounded-xl border border-warning/50 bg-warning/10 p-4">
          <Hand className="size-5 text-warning" />
          <div className="min-w-0 flex-1">
            <div className="font-semibold">The agent is waiting for your decision</div>
            <div className="text-sm text-muted">
              Nothing runs past this gate until a person approves. Review the summary below.
            </div>
          </div>
          <Button variant="warning" onClick={onReview}>
            Review & decide
          </Button>
        </div>
        {list.map((a) => (
          <Card key={a.id} className="p-4">
            <ArtifactHeader a={a} />
            <ArtifactBody a={a} />
          </Card>
        ))}
      </div>
    );
  } else if (list.length === 0) {
    body =
      state === 'active' ? (
        <div className="grid place-items-center gap-3 py-16 text-center">
          <AgentThinking label={`${stage.label}…`} />
          <p className="max-w-sm text-sm text-muted">{stage.description}</p>
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
            <ArtifactHeader a={a} traceId={traceId} />
            <ArtifactBody a={a} />
          </Tabs.Content>
        ))}
      </Tabs>
    );
  } else {
    body = (
      <div className="space-y-6">
        {list.map((a) => (
          <div key={a.id}>
            <ArtifactHeader a={a} traceId={traceId} />
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
        {body}
      </motion.div>
    </AnimatePresence>
  );
}
