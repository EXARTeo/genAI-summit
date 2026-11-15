// Written from scratch: a one-cell status + progress for an audit row (one smooth bar, toned
// by the run's state: no per-step segments, 18 of them read as noise).
import { CheckCircle2, CircleAlert, CircleX, Hourglass } from 'lucide-react';
import { cn } from '@/shared/lib/utils';
import { AgentThinking, Tooltip } from '@/shared/ui';
import { auditPhase, currentStep, failureReason, formatRunTime, runSeconds } from '../../lib/auditList';
import { STAGES } from '../../lib/pipeline';
import type { Audit } from '../../lib/types';

// Full class names (Tailwind only sees literal strings).
const FILL = { running: 'bg-primary', waiting: 'bg-warning', done: 'bg-success', failed: 'bg-danger' };

export function RunProgress({ audit }: { audit: Audit }) {
  const phase = auditPhase(audit);
  const step = currentStep(audit);
  const total = STAGES.length;
  const doneSteps = phase === 'done' ? total : step.n - 1;
  const reason = phase === 'failed' ? failureReason(audit.data) : null;
  const time = formatRunTime(runSeconds(audit));

  return (
    <div className="min-w-0 space-y-1.5">
      <div
        className="h-1.5 overflow-hidden rounded-full bg-surface-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={doneSteps}
        aria-label={`${doneSteps} of ${total} steps done`}
      >
        <div
          className={cn(
            'h-full rounded-full transition-[width] duration-500 ease-out',
            FILL[phase],
            phase === 'running' && 'motion-safe:animate-pulse',
          )}
          style={{ width: `${Math.max(phase === 'done' ? 100 : 4, Math.round((doneSteps / total) * 100))}%` }}
        />
      </div>
      <div className="flex min-w-0 items-center gap-1.5 text-xs">
        {phase === 'running' && (
          <AgentThinking
            size="sm"
            label={
              <span>
                Step {step.n} of {total} · {step.label}
              </span>
            }
          />
        )}
        {phase === 'waiting' && (
          <>
            <Hourglass className="size-3.5 shrink-0 text-warning" />
            <span className="truncate">
              <span className="font-medium text-warning">Waiting for you</span>
              <span className="text-muted">
                {' '}
                · Step {step.n} of {total} · {step.label}
              </span>
            </span>
          </>
        )}
        {phase === 'done' && (
          <>
            <CheckCircle2 className="size-3.5 shrink-0 text-success" />
            <span className="num truncate">
              <span className="font-medium text-success">Done</span>
              <span className="text-muted">
                {' '}
                · {total} steps{time && ` · ${time}`}
              </span>
            </span>
          </>
        )}
        {phase === 'failed' && (
          <Tooltip content={reason} disabled={!reason}>
            <span className="flex min-w-0 items-center gap-1.5">
              <CircleX className="size-3.5 shrink-0 text-danger" />
              <span className="truncate">
                <span className="font-medium text-danger">Failed</span>
                <span className="text-muted"> · at {step.label}</span>
              </span>
              {reason && <CircleAlert className="size-3 shrink-0 text-muted" />}
            </span>
          </Tooltip>
        )}
      </div>
    </div>
  );
}
