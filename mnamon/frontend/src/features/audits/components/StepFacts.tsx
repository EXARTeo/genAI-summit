import { Brain, History, PenLine, Scale } from 'lucide-react';
import type { ReactNode } from 'react';
import { formatRelative } from '@/shared/lib/format';
import { Badge, StatusPill, Tooltip } from '@/shared/ui';
import { artifactVersions, reviewedScenarios, searchDrivers, stepMemory, toScenarios } from '../lib/adapters';
import { REDO_LOOPS } from '../lib/graph';
import { formatDuration, latestByKind, type StageDef, type StepState } from '../lib/pipeline';
import type { AuditDetail } from '../lib/types';
import { DASH } from './artifact_parts/common';
import { ReviewBadge } from './artifact_parts/PlanViews';
import { actorLabel } from '@/shared/lib/labels';

const STATE_PILL: Record<StepState, { status: string; label: string }> = {
  done: { status: 'done', label: 'Done' },
  active: { status: 'running', label: 'Running' },
  pending: { status: 'pending', label: 'Pending' },
  blocked: { status: 'failed', label: 'Failed' },
  'needs-approval': { status: 'needs_approval', label: 'Waiting for you' },
};

function Fact({ label, icon, children }: { label: string; icon?: ReactNode; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-center gap-1.5 text-2xs font-medium text-muted [&_svg]:size-3">
        {icon}
        {label}
      </div>
      <div className="text-xs">{children}</div>
    </div>
  );
}

/** Everything about one step: status, times, memory, redo history, gate decisions, judge review. */
export function StepFacts({
  audit,
  stage,
  state,
}: {
  audit: AuditDetail;
  stage: StageDef;
  state: StepState;
}) {
  const kinds: string[] = stage.gate ? [...stage.gate.reviews] : [...stage.kinds];
  const own = audit.artifacts.filter((a) => kinds.includes(a.kind));
  const times = own.map((a) => a.createdAt).sort();
  const updated = own.map((a) => a.updatedAt).sort();
  const memory = stepMemory(own);

  // Redo history: the artifacts this step rewrites, every version.
  const loop = REDO_LOOPS.find((l) => l.to === stage.id || l.from === stage.id);
  const versions = loop ? artifactVersions(audit.artifacts, [loop.kind]) : [];
  // Gate decisions: this gate's, or the gate that sends this step back.
  const gateId = stage.gate?.id ?? loop?.gate;
  const decisions = gateId ? audit.approvals.filter((p) => p.gate === gateId) : [];
  const sentBack = loop
    ? audit.approvals.filter((p) => p.gate === loop.gate && p.decision !== 'approved').length
    : 0;

  const scenarioArt = latestByKind(audit.artifacts).scenarios?.[0];
  const showReview =
    !!scenarioArt && ['plan_scenarios', 'analyse_scenarios', 'approve_scenarios'].includes(stage.id);
  const reviewed = showReview ? reviewedScenarios(toScenarios(scenarioArt.data)) : [];
  const candidatesArt = latestByKind(audit.artifacts).public_dataset_candidates?.[0];
  const search =
    stage.id === 'find_public_data' && candidatesArt
      ? searchDrivers(candidatesArt.data, scenarioArt?.data)
      : null;

  return (
    <div className="mb-5 grid gap-x-6 gap-y-4 rounded-lg border border-border bg-surface-muted/30 p-4 sm:grid-cols-2 xl:grid-cols-4">
      <Fact label="Status">
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill status={STATE_PILL[state].status} label={STATE_PILL[state].label} />
          {audit.data.stageDurations?.[stage.id] != null && (
            <span className="num text-muted">{formatDuration(audit.data.stageDurations[stage.id])}</span>
          )}
        </div>
      </Fact>
      <Fact label="Timestamps">
        {times.length ? (
          <span className="num text-muted">
            created {formatRelative(times[0])}
            {updated.length && updated[updated.length - 1] !== times[0]
              ? ` · updated ${formatRelative(updated[updated.length - 1])}`
              : ''}
          </span>
        ) : (
          <span className="text-muted">{DASH}</span>
        )}
      </Fact>
      <Fact label="Memory used" icon={<Brain />}>
        {memory.applied.length === 0 && memory.recorded.length === 0 ? (
          <span className="text-muted">{DASH}</span>
        ) : (
          <ul className="space-y-0.5 font-mono text-2xs">
            {memory.applied.map((m) => (
              <li key={`a-${m}`} className="[overflow-wrap:anywhere]">
                <span className="text-info">read</span> {m}
              </li>
            ))}
            {memory.recorded.map((m) => (
              <li key={`r-${m}`} className="[overflow-wrap:anywhere]">
                <span className="text-primary">wrote</span> {m}
              </li>
            ))}
          </ul>
        )}
      </Fact>
      <Fact label="Redo history" icon={<History />}>
        {versions.length <= 1 ? (
          <span className="text-muted">
            {!loop
              ? DASH
              : sentBack > 0
                ? `Sent back ${sentBack}× at the gate; the redo is in progress`
                : 'No redo'}
          </span>
        ) : (
          <ul className="space-y-0.5">
            {versions.map((v) => (
              <li key={v.id} className="flex flex-wrap items-center gap-1.5">
                <span className="num font-mono">
                  {v.kind} v{v.version}
                </span>
                <StatusPill status={v.status} />
                <span className="num text-2xs text-muted">{formatRelative(v.createdAt)}</span>
              </li>
            ))}
          </ul>
        )}
      </Fact>
      {(gateId || decisions.length > 0) && (
        <div className="sm:col-span-2 xl:col-span-4">
          <Fact label="Gate decisions" icon={<Scale />}>
            {decisions.length === 0 ? (
              <span className="text-muted">No decision yet</span>
            ) : (
              <ul className="space-y-1.5">
                {decisions.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                    <StatusPill status={d.decision} />
                    {d.reasonCategory && <Badge>{d.reasonCategory.replace(/_/g, ' ')}</Badge>}
                    <span className="num text-2xs text-muted">
                      {actorLabel(d.decidedBy)} · {formatRelative(d.at)}
                    </span>
                    {d.comment && <span className="basis-full text-muted">“{d.comment}”</span>}
                  </li>
                ))}
              </ul>
            )}
          </Fact>
        </div>
      )}
      {search && (
        <div className="sm:col-span-2 xl:col-span-4">
          <Fact
            label={
              search.explicit
                ? 'Scenarios that drove the search'
                : 'Scenarios behind the search (by the fields they need)'
            }
          >
            {search.drivers.length === 0 ? (
              <span className="text-muted">{DASH}</span>
            ) : (
              <ul className="grid gap-1 sm:grid-cols-2">
                {search.drivers.map((d) => (
                  <li key={d.id} className="min-w-0">
                    <span className="font-mono text-2xs text-muted">{d.id}</span>{' '}
                    <span>{d.title ?? DASH}</span>
                    {d.fields.length > 0 && (
                      <span className="block font-mono text-2xs text-muted">{d.fields.join(', ')}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Fact>
        </div>
      )}
      {reviewed.length > 0 && (
        <div className="sm:col-span-2 xl:col-span-4">
          <Fact label="Scenario relevance review" icon={<PenLine />}>
            <div className="flex flex-wrap gap-1.5">
              {reviewed.map((s) => (
                <Tooltip
                  key={s.id}
                  content={<span className="block max-w-xs">{s.review.rationale ?? DASH}</span>}
                >
                  <span className="inline-flex items-center gap-1">
                    <span className="font-mono text-2xs text-muted">{s.id}</span>
                    <ReviewBadge review={s.review} compact />
                  </span>
                </Tooltip>
              ))}
            </div>
          </Fact>
        </div>
      )}
    </div>
  );
}
