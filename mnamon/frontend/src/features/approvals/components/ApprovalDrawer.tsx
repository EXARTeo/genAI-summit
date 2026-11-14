import { AnimatePresence, motion } from 'framer-motion';
import { Check, MessageSquareWarning, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { ArtifactBody } from '@/features/audits/components/ArtifactPanel';
import { TraceLink } from '@/features/audits/components/artifact_parts/common';
import { PublicCandidatesView } from '@/features/audits/components/artifact_parts/PlanViews';
import { GateCards, ProvenanceYaml } from '@/features/audits/components/artifact_parts/SpecViews';
import { useAudit, useDecideGate } from '@/features/audits/hooks/useAudits';
import {
  auditKbVersion,
  toDatasetAnalysis,
  toGenerationSpec,
  toPublicCandidates,
  toScenarioAnalysis,
} from '@/features/audits/lib/adapters';
import { latestByKind, gateStage } from '@/features/audits/lib/pipeline';
import { canApproveDataset, overallGateStatus } from '@/features/audits/lib/styling';
import type { Decision } from '@/features/audits/lib/types';
import { cn } from '@/shared/lib/utils';
import { Badge, Button, ErrorState, Field, Sheet, Skeleton, Tabs, Textarea, toast } from '@/shared/ui';
import {
  DECISIONS,
  EMPTY_DRAFT,
  REASONS,
  publicDataEdits,
  toApprovalIn,
  validateDraft,
  type DecisionDraft,
} from '../lib/approvals';

export interface ApprovalDrawerProps {
  auditId: string | null;
  gate: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Calm success state after an approval: one ripple, a drawn check, one line of copy. */
function ApprovedBurst() {
  return (
    <motion.div
      className="pointer-events-none absolute inset-0 z-10 grid place-items-center bg-surface/90"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18 }}
    >
      <div className="flex flex-col items-center gap-4">
        <div className="relative grid place-items-center">
          <motion.span
            className="absolute size-14 rounded-full border border-primary"
            initial={{ scale: 1, opacity: 0.6 }}
            animate={{ scale: 1.9, opacity: 0 }}
            transition={{ duration: 0.9, ease: 'easeOut' }}
          />
          <motion.span
            className="grid size-14 place-items-center rounded-full bg-primary text-primary-foreground"
            initial={{ scale: 0.7, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
          >
            <svg viewBox="0 0 24 24" className="size-7" fill="none">
              <motion.path
                d="M5 12.5l4.5 4.5L19 7.5"
                stroke="currentColor"
                strokeWidth={2.5}
                strokeLinecap="round"
                strokeLinejoin="round"
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.35, delay: 0.12 }}
              />
            </svg>
          </motion.span>
        </div>
        <motion.div
          className="text-center"
          initial={{ y: 4, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.2, duration: 0.2 }}
        >
          <div className="text-base font-semibold">Approved</div>
          <div className="text-sm text-muted">The agent continues with the next step.</div>
        </motion.div>
      </div>
    </motion.div>
  );
}

const DECISION_ICON = { approved: Check, changes_requested: MessageSquareWarning, rejected: X };
const DECISION_VARIANT = { approved: 'primary', changes_requested: 'warning', rejected: 'danger' } as const;
const DECISION_COPY: Record<Decision, { effect: string; submit: string; on: string }> = {
  approved: {
    effect: 'The agent continues past this gate.',
    submit: 'Approve and continue',
    on: 'border-primary/70 bg-primary/[0.06] [&_.icon]:bg-primary [&_.icon]:text-primary-foreground',
  },
  changes_requested: {
    effect: 'The agent revises and asks you again.',
    submit: 'Request changes',
    on: 'border-warning/70 bg-warning/[0.06] [&_.icon]:bg-warning [&_.icon]:text-warning-foreground',
  },
  rejected: {
    effect: 'The run stops here.',
    submit: 'Reject run',
    on: 'border-danger/70 bg-danger/[0.06] [&_.icon]:bg-danger [&_.icon]:text-danger-foreground',
  },
};

/** The public_data gate never stops the run: anything but approve means zero-shot. */
const PUBLIC_DATA_COPY: Record<Decision, { effect: string; submit: string }> = {
  approved: { effect: 'Fetch the picked dataset as the reference sample.', submit: 'Use this dataset' },
  changes_requested: { effect: 'Skip public data; generate zero-shot.', submit: 'Skip public data' },
  rejected: { effect: 'No public data; generate zero-shot. The run continues.', submit: 'Go zero-shot' },
};

export function ApprovalDrawer({ auditId, gate, open, onOpenChange }: ApprovalDrawerProps) {
  const { data: audit, isLoading, error, refetch } = useAudit(auditId ?? undefined);
  const decide = useDecideGate(auditId ?? '');
  const [draft, setDraft] = useState<DecisionDraft>(EMPTY_DRAFT);
  const [touched, setTouched] = useState(false);
  const [burst, setBurst] = useState(false);
  const [pick, setPick] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setDraft(EMPTY_DRAFT);
      setTouched(false);
      setBurst(false);
      setPick(null);
    }
  }, [open, auditId, gate]);

  const stage = gate ? gateStage(gate) : undefined;
  const by = latestByKind(audit?.artifacts ?? []);
  const first = (k: string) => by[k]?.[0]?.data;
  const datasetAnalysis = first('dataset_analysis')
    ? toDatasetAnalysis(first('dataset_analysis'))
    : undefined;
  const spec = first('generation_spec') ? toGenerationSpec(first('generation_spec')) : undefined;
  const scenarioAnalysis = first('scenario_analysis')
    ? toScenarioAnalysis(first('scenario_analysis'))
    : undefined;
  const candidates =
    gate === 'public_data' && first('public_dataset_candidates')
      ? toPublicCandidates(first('public_dataset_candidates'))
      : undefined;
  const reviewed = (stage?.gate?.reviews ?? []).flatMap((k) => by[k] ?? []);
  const blocked =
    gate === 'datasets' && datasetAnalysis && Object.keys(datasetAnalysis.gates).length > 0
      ? !canApproveDataset(datasetAnalysis.gates)
      : false;
  const needsPick = gate === 'public_data' && draft.decision === 'approved' && !pick;
  const errors = [
    ...validateDraft(draft),
    ...(needsPick ? ['Pick a dataset to approve, or reject for zero-shot.'] : []),
  ];
  const copy = (d: Decision) =>
    gate === 'public_data' ? { ...DECISION_COPY[d], ...PUBLIC_DATA_COPY[d] } : DECISION_COPY[d];

  const submit = () => {
    setTouched(true);
    if (!gate || errors.length) return;
    const edits = gate === 'public_data' && draft.decision === 'approved' ? publicDataEdits(pick) : {};
    decide.mutate(toApprovalIn(gate, draft, reviewed[0]?.id, edits), {
      onSuccess: () => {
        if (draft.decision === 'approved') {
          setBurst(true);
          setTimeout(() => onOpenChange(false), 1500);
        } else {
          onOpenChange(false);
        }
        toast.success(`${DECISIONS[draft.decision!].label}: ${stage?.label ?? gate}`);
      },
      onError: (e) => toast.error('Could not record the decision', { description: (e as Error).message }),
    });
  };

  const choose = (d: Decision) => setDraft((x) => ({ ...x, decision: d }));

  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      width="w-[min(46rem,100vw)]"
      title={stage ? `${stage.label}` : 'Approval'}
      description={
        audit ? `${audit.systemId} · ${audit.data.systemName ?? ''} · ${audit.data.title ?? ''}` : undefined
      }
      footer={
        <div className="flex w-full flex-wrap items-center gap-2">
          {touched && errors.length > 0 && <span className="mr-auto text-xs text-danger">{errors[0]}</span>}
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Later
          </Button>
          <Button
            variant={draft.decision ? DECISION_VARIANT[draft.decision] : 'primary'}
            onClick={submit}
            loading={decide.isPending}
            disabled={!draft.decision || (draft.decision === 'approved' && blocked)}
          >
            {draft.decision ? copy(draft.decision).submit : 'Choose a decision'}
          </Button>
        </div>
      }
    >
      <div className="relative">
        <AnimatePresence>{burst && <ApprovedBurst />}</AnimatePresence>
        {isLoading && <Skeleton className="h-64 w-full" />}
        {error && <ErrorState error={error} onRetry={() => void refetch()} compact />}
        {audit && (
          <div className="space-y-5">
            <div className="space-y-0.5 text-xs text-muted">
              <div className="num flex items-center gap-3">
                <span className="font-mono">{audit.id}</span>
                <span className="font-mono">kb {auditKbVersion(audit) ?? '–'}</span>
                <TraceLink
                  className="ml-auto"
                  traceId={audit.data.stageTraces?.[stage?.id ?? ''] ?? audit.data.traceId}
                  label="Step trace"
                />
              </div>
              {audit.data.trigger && audit.data.trigger !== 'manual' && (
                <div className="truncate">Triggered by {audit.data.trigger}</div>
              )}
            </div>

            <Tabs defaultValue="summary">
              <Tabs.List>
                <Tabs.Trigger value="summary">Summary</Tabs.Trigger>
                <Tabs.Trigger value="analysis">Analysis</Tabs.Trigger>
                <Tabs.Trigger value="diff">Diffs</Tabs.Trigger>
              </Tabs.List>
              <Tabs.Content value="summary" className="space-y-3">
                {gate === 'datasets' && datasetAnalysis && (
                  <>
                    <div className="flex items-center gap-2 text-sm font-medium">
                      Validation gates{' '}
                      <Badge
                        tone={
                          overallGateStatus(datasetAnalysis.gates) === 'pass'
                            ? 'success'
                            : overallGateStatus(datasetAnalysis.gates) === 'warn'
                              ? 'warning'
                              : 'danger'
                        }
                      >
                        {overallGateStatus(datasetAnalysis.gates)}
                      </Badge>
                      {blocked && (
                        <span className="text-danger">A blocking gate failed: approval is disabled.</span>
                      )}
                    </div>
                    <GateCards gates={datasetAnalysis.gates} />
                    {spec && spec.assumptions.some((a) => a.provenance === 'llm_assumption') && (
                      <div className="rounded-lg border border-border p-3 text-sm">
                        <div className="mb-1.5 text-xs font-medium text-muted">
                          Check these: values the LLM assumed, not taken from your documents
                        </div>
                        <ul className="space-y-1">
                          {spec.assumptions
                            .filter((a) => a.provenance === 'llm_assumption')
                            .map((a) => (
                              <li key={a.field} className="flex gap-2">
                                <span className="mt-2 size-1 shrink-0 rounded-full bg-warning" />
                                <span>
                                  <span className="font-mono text-xs">{a.field}</span>{' '}
                                  <span className="text-muted">·</span> {a.what ?? '–'}
                                </span>
                              </li>
                            ))}
                        </ul>
                      </div>
                    )}
                  </>
                )}
                {gate === 'scenarios' && scenarioAnalysis && (
                  <p className="rounded-lg border border-border bg-surface-muted/60 p-3 text-sm">
                    {scenarioAnalysis.summary ?? '–'}
                  </p>
                )}
                {gate === 'public_data' && candidates && (
                  <>
                    <p className="text-sm text-muted">
                      Pick the public dataset the generator uses as a reference sample, then approve. Reject
                      to generate zero-shot from the data dictionary; the run continues either way.
                    </p>
                    <PublicCandidatesView data={candidates} selected={pick} onSelect={setPick} />
                  </>
                )}
              </Tabs.Content>
              <Tabs.Content value="analysis" className="space-y-6">
                {reviewed.map((a) => (
                  <div key={a.id}>
                    <ArtifactBody a={a} />
                  </div>
                ))}
              </Tabs.Content>
              <Tabs.Content value="diff" className="space-y-3">
                {gate === 'datasets' && spec ? (
                  <>
                    {spec.diff?.map((d) => (
                      <div key={d.field} className="rounded-lg border border-border p-2 font-mono text-xs">
                        <div className="text-muted">{d.field}</div>
                        <div className="text-danger">- {d.before}</div>
                        <div className="text-success">+ {d.after}</div>
                      </div>
                    ))}
                    {spec.yaml && <ProvenanceYaml yaml={spec.yaml} />}
                  </>
                ) : scenarioAnalysis?.diff ? (
                  <div className="space-y-1 font-mono text-xs">
                    {scenarioAnalysis.diff.added.map((d) => (
                      <div key={d} className="text-success">
                        + {d}
                      </div>
                    ))}
                    {scenarioAnalysis.diff.removed.map((d) => (
                      <div key={d} className="text-danger">
                        - {d}
                      </div>
                    ))}
                    {scenarioAnalysis.diff.changed.map((d) => (
                      <div key={d} className="text-warning">
                        ~ {d}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted">No earlier approved version to compare with.</p>
                )}
              </Tabs.Content>
            </Tabs>

            <div className="space-y-4 border-t border-border pt-5">
              <div>
                <h3 className="text-sm font-semibold">Your decision</h3>
                <p className="text-xs text-muted">
                  Logged with your name; nothing runs past the gate until you decide.
                </p>
              </div>
              <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Decision">
                {(Object.keys(DECISIONS) as Decision[]).map((d) => {
                  const Icon = DECISION_ICON[d];
                  const on = draft.decision === d;
                  const disabled = d === 'approved' && blocked;
                  return (
                    <button
                      key={d}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      disabled={disabled}
                      onClick={() => choose(d)}
                      className={cn(
                        'flex items-start gap-2.5 rounded-lg border p-3 text-left transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50',
                        on ? copy(d).on : 'border-border hover:border-text/25',
                      )}
                    >
                      <span className="icon grid size-6 shrink-0 place-items-center rounded-full bg-surface-muted text-muted transition-colors">
                        <Icon className="size-3.5" />
                      </span>
                      <span className="min-w-0">
                        <span className="block text-sm font-medium">{DECISIONS[d].label}</span>
                        <span className="block text-2xs text-muted">{copy(d).effect}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
              <Field
                label="Reason category"
                error={touched && !draft.reasonCategory ? 'Required' : undefined}
                hint={REASONS.find((r) => r.value === draft.reasonCategory)?.hint}
              >
                <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Reason category">
                  {REASONS.map((r) => {
                    const on = draft.reasonCategory === r.value;
                    return (
                      <button
                        key={r.value}
                        type="button"
                        role="radio"
                        aria-checked={on}
                        title={r.hint}
                        onClick={() => setDraft((x) => ({ ...x, reasonCategory: r.value }))}
                        className={cn(
                          'h-7 rounded-full border px-2.5 text-xs font-medium transition-colors duration-150',
                          on
                            ? 'border-text/80 bg-text text-background'
                            : 'border-border text-muted hover:border-text/25 hover:text-text',
                        )}
                      >
                        {r.label}
                      </button>
                    );
                  })}
                </div>
              </Field>
              <Field label="Comment">
                <Textarea
                  rows={3}
                  value={draft.comment}
                  onChange={(e) => setDraft((x) => ({ ...x, comment: e.target.value }))}
                  placeholder={draft.decision === 'approved' ? 'Optional note' : 'What should change?'}
                />
              </Field>
            </div>
          </div>
        )}
      </div>
    </Sheet>
  );
}
