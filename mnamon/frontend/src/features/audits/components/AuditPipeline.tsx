import '@/styles/audit-flow.css';
import { useMemo, type KeyboardEvent } from 'react';
import { cn } from '@/shared/lib/utils';
import { PHASES } from '../lib/graph';
import { STAGES, stepStates } from '../lib/pipeline';
import { stepSummary } from '../lib/stepMeta';
import type { AuditDetail } from '../lib/types';
import { StepCard } from './pipeline_parts/StepCard';

export interface AuditPipelineProps {
  audit: AuditDetail;
  selected: string;
  onSelect: (stageId: string) => void;
  onReview: () => void;
}

/**
 * The pipeline as a vertical stepper (phones and narrow screens): the graph's cards, in the
 * same three phases, joined by a rail that turns primary as steps complete.
 */
export function AuditPipeline({ audit, selected, onSelect, onReview }: AuditPipelineProps) {
  const states = stepStates(audit);
  const summaries = useMemo(
    () => Object.fromEntries(STAGES.map((s) => [s.id, stepSummary(s.id, audit)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [audit.updatedAt, audit.artifacts.length, audit.approvals.length],
  );
  const key = (id: string) => (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onSelect(id);
    }
  };

  return (
    <div className="space-y-5">
      {PHASES.map((p) => {
        const done = p.stages.filter((s) => states[s] === 'done').length;
        return (
          <section key={p.id} aria-label={p.label}>
            <div className="mb-2.5 flex items-center justify-between px-1">
              <h3 className="text-[13.5px] font-semibold tracking-tight">{p.label}</h3>
              <span
                className={cn(
                  'num rounded-full px-2 py-0.5 text-xs font-medium',
                  done === p.stages.length ? 'bg-success/12 text-success' : 'bg-surface-sunken text-muted',
                )}
              >
                {done}/{p.stages.length}
              </span>
            </div>
            <ol>
              {p.stages.map((id, i) => {
                const stage = STAGES.find((s) => s.id === id)!;
                const last = i === p.stages.length - 1;
                return (
                  <li key={id} className="relative">
                    <div
                      role="button"
                      tabIndex={0}
                      aria-current={id === selected ? 'step' : undefined}
                      aria-label={`Step ${STAGES.indexOf(stage) + 1}: ${stage.label}`}
                      onClick={() => onSelect(id)}
                      onKeyDown={key(id)}
                      className="rounded-[1.1rem] outline-none focus-visible:ring-2 focus-visible:ring-primary/70 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                    >
                      <StepCard
                        stage={stage}
                        state={states[id]}
                        summary={summaries[id]}
                        selected={id === selected}
                        onReview={onReview}
                      />
                    </div>
                    {!last && (
                      <span
                        aria-hidden
                        className="audit-step-rail ml-[31px] block h-3.5 w-0.5 rounded-full"
                        data-done={states[id] === 'done' ? 'true' : 'false'}
                      />
                    )}
                  </li>
                );
              })}
            </ol>
          </section>
        );
      })}
    </div>
  );
}
