import { motion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import { cn } from '@/shared/lib/utils';
import { AgentThinking, Button, Stepper, type StepItem } from '@/shared/ui';
import { STAGES, formatDuration, stepStates, type StepState } from '../lib/pipeline';
import type { AuditDetail } from '../lib/types';
import { TraceLink } from './artifact_parts/common';

export interface AuditPipelineProps {
  audit: AuditDetail;
  selected: string;
  onSelect: (stageId: string) => void;
  onReview: () => void;
}

/** Remember which steps just turned done, to flash them once. */
function useJustDone(states: Record<string, StepState>): Set<string> {
  const prev = useRef(states);
  const [flash, setFlash] = useState<Set<string>>(new Set());
  const key = Object.values(states).join(',');
  useEffect(() => {
    const done = Object.keys(states).filter((k) => states[k] === 'done' && prev.current[k] !== 'done');
    prev.current = states;
    if (done.length) setFlash(new Set(done));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  useEffect(() => {
    if (!flash.size) return;
    const t = setTimeout(() => setFlash(new Set()), 1400);
    return () => clearTimeout(t);
  }, [flash]);
  return flash;
}

/** The live vertical Stepper of the engineer pipeline. */
export function AuditPipeline({ audit, selected, onSelect, onReview }: AuditPipelineProps) {
  const states = stepStates(audit);
  const flash = useJustDone(states);
  const durations = audit.data.stageDurations ?? {};
  const traces = audit.data.stageTraces ?? {};

  const steps: StepItem[] = STAGES.map((s) => {
    const state = states[s.id];
    const isSel = s.id === selected;
    return {
      id: s.id,
      state,
      title: (
        <span
          className={cn(
            'relative -mx-1.5 inline-flex items-center gap-2 rounded-md px-1.5 py-0.5 transition-colors',
            isSel && 'bg-primary/10 text-primary',
          )}
        >
          {s.gate && <span className="text-warning">⏸</span>}
          {s.label}
          {flash.has(s.id) && (
            <motion.span
              className="absolute inset-0 rounded-md bg-success/25"
              initial={{ opacity: 1, scale: 0.9 }}
              animate={{ opacity: 0, scale: 1.15 }}
              transition={{ duration: 1.2 }}
            />
          )}
        </span>
      ),
      description: isSel || state === 'active' || state === 'needs-approval' ? s.description : undefined,
      meta: (
        <span className="flex items-center gap-2">
          {state === 'done' && durations[s.id] != null && (
            <span className="font-mono">{formatDuration(durations[s.id])}</span>
          )}
          {state !== 'pending' && <TraceLink traceId={traces[s.id]} label="trace" />}
        </span>
      ),
      content:
        state === 'active' ? (
          <AgentThinking label="Agent working…" />
        ) : state === 'needs-approval' ? (
          <Button size="sm" variant="warning" onClick={onReview}>
            Review & decide
          </Button>
        ) : undefined,
    };
  });

  return <Stepper steps={steps} onStepClick={onSelect} />;
}
