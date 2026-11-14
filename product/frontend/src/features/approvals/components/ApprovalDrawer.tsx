import { AnimatePresence, motion } from 'framer-motion';
import { Brain, Check, MessageSquareWarning, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { ArtifactBody } from '@/features/audits/components/ArtifactPanel';
import { TraceLink } from '@/features/audits/components/artifact_parts/common';
import { GateCards, ProvenanceYaml } from '@/features/audits/components/artifact_parts/SpecViews';
import { useAudit, useDecideGate } from '@/features/audits/hooks/useAudits';
import { latestByKind, gateStage } from '@/features/audits/lib/pipeline';
import { canApproveDataset, overallGateStatus } from '@/features/audits/lib/styling';
import type {
  DatasetAnalysisData,
  Decision,
  GenerationSpecData,
  ScenarioAnalysisData,
} from '@/features/audits/lib/types';
import { cn } from '@/shared/lib/utils';
import {
  Badge,
  Button,
  ErrorState,
  Field,
  KeyValue,
  Select,
  Sheet,
  Skeleton,
  Switch,
  Tabs,
  Textarea,
  toast,
} from '@/shared/ui';
import {
  DECISIONS,
  EMPTY_DRAFT,
  REASONS,
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

/** Full-screen check that pops after an approval. */
function ApprovedBurst() {
  return (
    <motion.div
      className="pointer-events-none absolute inset-0 z-10 grid place-items-center bg-surface/80 backdrop-blur-sm"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      <div className="relative grid place-items-center">
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="absolute size-24 rounded-full border-2 border-success"
            initial={{ scale: 0.6, opacity: 0.8 }}
            animate={{ scale: 2.4 + i * 0.5, opacity: 0 }}
            transition={{ duration: 1.1, delay: i * 0.15, ease: 'easeOut' }}
          />
        ))}
        <motion.span
          className="grid size-24 place-items-center rounded-full bg-success text-white shadow-lift"
          initial={{ scale: 0, rotate: -90 }}
          animate={{ scale: 1, rotate: 0 }}
          transition={{ type: 'spring', stiffness: 360, damping: 16 }}
        >
          <svg viewBox="0 0 24 24" className="size-12" fill="none">
            <motion.path
              d="M5 12.5l4.5 4.5L19 7.5"
              stroke="currentColor"
              strokeWidth={3}
              strokeLinecap="round"
              strokeLinejoin="round"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.45, delay: 0.2 }}
            />
          </svg>
        </motion.span>
        <motion.div
          className="absolute top-32 whitespace-nowrap text-lg font-semibold"
          initial={{ y: 8, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.35 }}
        >
          Approved. The agent continues.
        </motion.div>
      </div>
    </motion.div>
  );
}

const DECISION_ICON = { approved: Check, changes_requested: MessageSquareWarning, rejected: X };
const DECISION_VARIANT = { approved: 'primary', changes_requested: 'warning', rejected: 'danger' } as const;

export function ApprovalDrawer({ auditId, gate, open, onOpenChange }: ApprovalDrawerProps) {
  const { data: audit, isLoading, error, refetch } = useAudit(auditId ?? undefined);
  const decide = useDecideGate(auditId ?? '');
  const [draft, setDraft] = useState<DecisionDraft>(EMPTY_DRAFT);
  const [touched, setTouched] = useState(false);
  const [burst, setBurst] = useState(false);

  useEffect(() => {
    if (open) {
      setDraft(EMPTY_DRAFT);
      setTouched(false);
      setBurst(false);
    }
  }, [open, auditId, gate]);

  const stage = gate ? gateStage(gate) : undefined;
  const by = latestByKind(audit?.artifacts ?? []);
  const datasetAnalysis = by.dataset_analysis?.[0]?.data as DatasetAnalysisData | undefined;
  const spec = by.generation_spec?.[0]?.data as GenerationSpecData | undefined;
  const scenarioAnalysis = by.scenario_analysis?.[0]?.data as ScenarioAnalysisData | undefined;
  const reviewed = (stage?.gate?.reviews ?? []).flatMap((k) => by[k] ?? []);
  const blocked = gate === 'datasets' && datasetAnalysis ? !canApproveDataset(datasetAnalysis.gates) : false;
  const errors = validateDraft(draft);

  const submit = () => {
    setTouched(true);
    if (!gate || errors.length) return;
    decide.mutate(toApprovalIn(gate, draft, reviewed[0]?.id), {
      onSuccess: (res) => {
        if (draft.decision === 'approved') {
          setBurst(true);
          setTimeout(() => onOpenChange(false), 1500);
        } else {
          onOpenChange(false);
        }
        toast.success(`${DECISIONS[draft.decision!].label}: ${stage?.label ?? gate}`, {
          description: res.memoryProposalPath
            ? `Memory proposal written to ${res.memoryProposalPath}`
            : undefined,
        });
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
            onClick={submit}
            loading={decide.isPending}
            disabled={!draft.decision || (draft.decision === 'approved' && blocked)}
          >
            Submit decision
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
            <KeyValue
              columns={3}
              items={[
                { label: 'Audit', value: audit.id, mono: true },
                { label: 'kb_version', value: audit.data.kbVersion ?? '–', mono: true },
                { label: 'Trigger', value: audit.data.trigger ?? 'manual' },
              ]}
            />
            <TraceLink
              traceId={audit.data.stageTraces?.[stage?.id ?? ''] ?? audit.data.traceId}
              label="Open this step in Langfuse"
            />

            <Tabs defaultValue="summary">
              <Tabs.List>
                <Tabs.Trigger value="summary">Summary</Tabs.Trigger>
                <Tabs.Trigger value="analysis">Analysis</Tabs.Trigger>
                <Tabs.Trigger value="diff">Diffs</Tabs.Trigger>
              </Tabs.List>
              <Tabs.Content value="summary" className="space-y-3">
                {gate === 'datasets' && datasetAnalysis && (
                  <>
                    <div className="flex items-center gap-2 text-sm">
                      Gates overall{' '}
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
                    {spec && spec.assumptions.length > 0 && (
                      <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
                        <div className="font-medium text-warning">LLM assumptions in the spec</div>
                        {spec.assumptions.map((a) => (
                          <div key={a.field}>
                            <span className="font-mono text-xs">{a.field}</span> · {a.what}
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
                {gate === 'scenarios' && scenarioAnalysis && (
                  <p className="rounded-lg border border-border bg-surface-muted/60 p-3 text-sm">
                    {scenarioAnalysis.summary}
                  </p>
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
                    <ProvenanceYaml yaml={spec.yaml} />
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

            <div className="space-y-4 rounded-xl border border-border bg-surface-muted/40 p-4">
              <div className="grid grid-cols-3 gap-2">
                {(Object.keys(DECISIONS) as Decision[]).map((d) => {
                  const Icon = DECISION_ICON[d];
                  const on = draft.decision === d;
                  return (
                    <motion.div key={d} whileTap={{ scale: 0.96 }}>
                      <Button
                        className={cn('w-full', !on && 'opacity-80')}
                        variant={on ? DECISION_VARIANT[d] : 'secondary'}
                        leftIcon={<Icon />}
                        onClick={() => choose(d)}
                        disabled={d === 'approved' && blocked}
                        aria-pressed={on}
                      >
                        {DECISIONS[d].label}
                      </Button>
                    </motion.div>
                  );
                })}
              </div>
              <Field
                label="Reason category"
                error={touched && !draft.reasonCategory ? 'Required' : undefined}
                hint={REASONS.find((r) => r.value === draft.reasonCategory)?.hint}
              >
                <Select
                  value={draft.reasonCategory ?? undefined}
                  onValueChange={(v) =>
                    setDraft((x) => ({ ...x, reasonCategory: v as DecisionDraft['reasonCategory'] }))
                  }
                  options={REASONS.map((r) => ({ value: r.value, label: r.label, description: r.hint }))}
                  placeholder="Why this decision?"
                  aria-label="Reason category"
                />
              </Field>
              <Field label="Comment" hint="Becomes the memory's rationale if you save it.">
                <Textarea
                  rows={3}
                  value={draft.comment}
                  onChange={(e) => setDraft((x) => ({ ...x, comment: e.target.value }))}
                  placeholder={draft.decision === 'approved' ? 'Optional note' : 'What should change?'}
                />
              </Field>
              <div className="space-y-2 rounded-lg border border-border bg-surface p-3">
                <label className="flex items-center gap-3 text-sm">
                  <Switch
                    checked={draft.memoryScope !== 'none'}
                    onCheckedChange={(on) => setDraft((x) => ({ ...x, memoryScope: on ? 'system' : 'none' }))}
                  />
                  <Brain className="size-4 text-info" />
                  Save as memory for {audit.systemId}
                </label>
                {draft.memoryScope !== 'none' && (
                  <label className="flex items-center gap-3 pl-12 text-sm">
                    <Switch
                      checked={draft.memoryScope === 'org'}
                      onCheckedChange={(on) =>
                        setDraft((x) => ({ ...x, memoryScope: on ? 'org' : 'system' }))
                      }
                    />
                    Propose org-wide (the AI Officer approves)
                  </label>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </Sheet>
  );
}
