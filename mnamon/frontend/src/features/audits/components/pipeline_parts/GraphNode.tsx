import { Handle, Position } from '@xyflow/react';
import { Check, Hand, X } from 'lucide-react';
import { cn } from '@/shared/lib/utils';
import { Button } from '@/shared/ui';
import { GRAPH } from '../../lib/graph';
import type { StageDef, StepState } from '../../lib/pipeline';
import { STEP_HINT, STEP_ICON } from '../../lib/stepMeta';

// Built here: an agent-graph node (icon box, label under it) has no ready-made shadcn
// counterpart; the running light is mAgenticX's sub-agent card light (styles/audit-flow.css).

const STATE_LABEL: Record<StepState, string> = {
  done: 'Done',
  active: 'Running',
  pending: 'Not started',
  blocked: 'Failed',
  'needs-approval': 'Waiting for you',
};

const handle = 'audit-handle';

export interface GraphNodeProps {
  stage: StageDef;
  state: StepState;
  summary?: string;
  selected: boolean;
  onReview?: () => void;
}

/**
 * One pipeline step on the graph: a rounded box for an agent step, a circle for a human
 * gate. Running → the travelling light round the box and a shimmering "Running…"; a gate
 * that waits → the same light in amber and the decision button; done → a check badge.
 */
export function GraphNode({ stage, state, summary, selected, onReview }: GraphNodeProps) {
  const gate = !!stage.gate;
  const Icon = STEP_ICON[stage.id] ?? Check;
  const live = state === 'active' || state === 'needs-approval';
  const half = GRAPH.box / 2;
  return (
    <div
      className="pg-node flex h-full flex-col items-center"
      data-state={state}
      data-gate={gate ? 'true' : 'false'}
      data-selected={selected ? 'true' : 'false'}
    >
      <div className="pg-box-wrap relative" style={{ width: GRAPH.box, height: GRAPH.box }}>
        <Handle type="target" position={Position.Left} id="l" className={handle} style={{ top: half }} />
        <Handle type="source" position={Position.Right} id="r" className={handle} style={{ top: half }} />
        <Handle type="source" position={Position.Top} id="t-out" className={handle} />
        <Handle type="target" position={Position.Top} id="t-in" className={handle} />
        {live && <span className="pg-halo" aria-hidden />}
        <div className="pg-box relative grid size-full place-items-center">
          <span className="pg-box-sheen pointer-events-none absolute inset-0" aria-hidden />
          <Icon className="relative size-6" strokeWidth={1.75} aria-hidden />
        </div>
        {state === 'done' && (
          <span className="pg-badge bg-success text-success-foreground" aria-hidden>
            <Check strokeWidth={3.5} />
          </span>
        )}
        {state === 'blocked' && (
          <span className="pg-badge bg-danger text-danger-foreground" aria-hidden>
            <X strokeWidth={3.5} />
          </span>
        )}
        {state === 'needs-approval' && (
          <span className="pg-badge bg-warning text-warning-foreground" aria-hidden>
            <Hand strokeWidth={2.5} />
          </span>
        )}
      </div>

      <div className="mt-2.5 w-full px-2 text-center">
        <div className="pg-title truncate text-[13px] font-semibold leading-[18px] tracking-tight">
          {stage.label}
        </div>
        <div
          className={cn(
            'mt-0.5 line-clamp-2 text-[12px] leading-[16px]',
            state === 'active' && 'text-shimmer font-medium',
            state === 'needs-approval' && 'font-medium text-warning',
            state === 'blocked' && 'font-medium text-danger',
            !live && state !== 'blocked' && 'text-muted',
          )}
          title={summary ?? STEP_HINT[stage.id]}
        >
          {state === 'active'
            ? 'Running…'
            : state === 'needs-approval'
              ? 'Waiting for you'
              : state === 'blocked'
                ? 'Failed'
                : (summary ?? STEP_HINT[stage.id])}
        </div>
        <span className="sr-only">{STATE_LABEL[state]}</span>
      </div>

      {state === 'needs-approval' && onReview && (
        <Button
          size="sm"
          variant="warning"
          className="nodrag nopan mt-2 rounded-full px-3"
          leftIcon={<Hand />}
          onClick={(e) => {
            e.stopPropagation();
            onReview();
          }}
        >
          Review
        </Button>
      )}
    </div>
  );
}
