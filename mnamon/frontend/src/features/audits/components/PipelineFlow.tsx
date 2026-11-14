import {
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
} from '@xyflow/react';
import { useReducedMotion } from 'framer-motion';
import { Check, Hand, X } from 'lucide-react';
import { useEffect, useMemo, useRef, type KeyboardEvent } from 'react';
import { color } from '@/shared/lib/consts/ui';
import { cn } from '@/shared/lib/utils';
import { Button } from '@/shared/ui';
import { NODE_H, NODE_W, PHASES, graphModel, nodePosition, type EdgeState } from '../lib/graph';
import { STAGES, formatDuration, type StageDef, type StepState } from '../lib/pipeline';
import type { AuditDetail } from '../lib/types';

const STATE_LABEL: Record<StepState, string> = {
  done: 'Done',
  active: 'Running',
  pending: 'Pending',
  blocked: 'Failed',
  'needs-approval': 'Waiting for your decision',
};

type StepData = {
  stage: StageDef;
  index: number;
  state: StepState;
  selected: boolean;
  duration?: number;
  reduced: boolean;
  onOpen: (id: string) => void;
  onReview: () => void;
};
type PhaseData = { label: string };

const hidden = '!pointer-events-none !size-1 !min-h-0 !min-w-0 !border-0 !bg-transparent';

function StateIcon({ state, gate, reduced }: { state: StepState; gate: boolean; reduced: boolean }) {
  const base = 'relative grid size-7 shrink-0 place-items-center rounded-full';
  if (state === 'done')
    return (
      <span className={cn(base, 'bg-primary/15 text-primary')}>
        <Check className="size-3.5" strokeWidth={3} />
      </span>
    );
  if (state === 'active')
    return (
      <span className={cn(base, 'bg-primary/10')}>
        {!reduced && <span className="agent-orb absolute inset-0" />}
        <span className="size-2 rounded-full bg-primary" />
      </span>
    );
  if (state === 'needs-approval')
    return (
      <span className={cn(base, 'bg-warning text-warning-foreground', !reduced && 'approval-pulse')}>
        <Hand className="size-3.5" />
      </span>
    );
  if (state === 'blocked')
    return (
      <span className={cn(base, 'bg-danger/15 text-danger')}>
        <X className="size-3.5" strokeWidth={3} />
      </span>
    );
  return (
    <span className={cn(base, 'border border-dashed border-border text-muted')}>
      {gate ? <Hand className="size-3" /> : <span className="size-1.5 rounded-full bg-border" />}
    </span>
  );
}

/** One pipeline step. Focusable; Enter / Space opens its panel. Gates are pills with a hand. */
function StepNode({ data }: NodeProps<Node<StepData>>) {
  const { stage, state, selected, reduced } = data;
  const gate = !!stage.gate;
  const open = () => data.onOpen(stage.id);
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      open();
    }
  };
  const sub =
    state === 'done'
      ? data.duration != null
        ? formatDuration(data.duration)
        : 'done'
      : state === 'active'
        ? 'running'
        : state === 'needs-approval'
          ? 'waiting for you'
          : state === 'blocked'
            ? 'failed'
            : gate
              ? 'human gate'
              : 'pending';
  return (
    <div style={{ width: NODE_W }}>
      <Handle type="target" position={Position.Left} id="l" style={{ top: NODE_H / 2 }} className={hidden} />
      <Handle type="source" position={Position.Right} id="r" style={{ top: NODE_H / 2 }} className={hidden} />
      <Handle type="target" position={Position.Top} id="top-in" className={hidden} />
      <Handle
        type="target"
        position={Position.Top}
        id="top-redo"
        style={{ left: '28%' }}
        className={hidden}
      />
      <Handle type="source" position={Position.Top} id="top-out" style={{ left: '72%' }} className={hidden} />
      <Handle type="source" position={Position.Bottom} id="bottom-out" className={hidden} />
      <div
        role="button"
        tabIndex={0}
        aria-pressed={selected}
        aria-label={`Step ${data.index + 1}: ${stage.label}${gate ? ' (human gate)' : ''}, ${STATE_LABEL[state]}`}
        onClick={open}
        onKeyDown={onKey}
        style={{ minHeight: NODE_H }}
        className={cn(
          'flex w-full cursor-pointer items-center gap-2.5 border bg-surface px-3 py-2 text-left shadow-card outline-none transition-[box-shadow,border-color,background-color] duration-150',
          'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
          gate ? 'rounded-full' : 'rounded-xl',
          gate && state === 'pending' && 'border-dashed',
          state === 'done' && 'border-border',
          state === 'pending' && 'border-border bg-surface/70',
          state === 'active' && 'border-primary/60 ring-2 ring-primary/20',
          state === 'needs-approval' && 'border-warning bg-warning/[0.08] ring-2 ring-warning/25',
          state === 'blocked' && 'border-danger/60 bg-danger/[0.05]',
          selected && state !== 'needs-approval' && 'ring-2 ring-primary/45',
          'hover:border-text/25',
        )}
      >
        <StateIcon state={state} gate={gate} reduced={reduced} />
        <span className="min-w-0 flex-1">
          <span
            className={cn(
              'line-clamp-2 block text-[13px] font-medium leading-tight',
              state === 'pending' ? 'text-muted' : 'text-text',
              state === 'active' && !reduced && 'text-shimmer',
              state === 'needs-approval' && 'text-warning',
            )}
          >
            {stage.label}
          </span>
          <span className="num mt-0.5 block truncate text-2xs text-muted">
            {data.index + 1} · {sub}
          </span>
        </span>
      </div>
      {state === 'needs-approval' && (
        <div className="mt-1.5 flex justify-center">
          <Button
            size="sm"
            variant="warning"
            onClick={(e) => {
              e.stopPropagation();
              data.onReview();
            }}
          >
            Review & decide
          </Button>
        </div>
      )}
    </div>
  );
}

function PhaseNode({ data }: NodeProps<Node<PhaseData>>) {
  return (
    <div className="pointer-events-none whitespace-nowrap text-2xs font-semibold uppercase tracking-wider text-muted">
      {data.label}
    </div>
  );
}

const nodeTypes = { step: StepNode, phase: PhaseNode };

const EDGE_COLOR: Record<EdgeState, string> = {
  done: color('primary', 0.5),
  live: color('primary'),
  waiting: color('warning'),
  pending: color('border'),
};

export interface PipelineFlowProps {
  audit: AuditDetail;
  selected: string;
  onSelect: (stageId: string) => void;
  onReview: () => void;
}

/** The audit pipeline as a graph: three phase rows, live edges, gates as pills, redo loops. */
export function PipelineFlow({ audit, selected, onSelect, onReview }: PipelineFlowProps) {
  const reduced = !!useReducedMotion();
  const { states, edges: pe, redos } = graphModel(audit);
  const durations = audit.data.stageDurations ?? {};
  const key = `${Object.values(states).join()}|${selected}|${redos.map((r) => r.count).join()}|${reduced}`;

  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = [
      ...PHASES.map((p, row) => ({
        id: `phase-${row}`,
        type: 'phase',
        position: { x: 0, y: nodePosition(p.stages[0]).y - 24 },
        data: { label: p.label },
        selectable: false,
        focusable: false,
        draggable: false,
      })),
      ...STAGES.map((s, i) => ({
        id: s.id,
        type: 'step',
        position: nodePosition(s.id),
        data: {
          stage: s,
          index: i,
          state: states[s.id],
          selected: s.id === selected,
          duration: durations[s.id],
          reduced,
          onOpen: onSelect,
          onReview,
        } satisfies StepData,
        focusable: false,
        draggable: false,
      })),
    ];
    const edges: Edge[] = pe.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.wrap ? 'bottom-out' : 'r',
      targetHandle: 'l',
      type: 'smoothstep',
      animated: !reduced && (e.state === 'live' || e.state === 'waiting'),
      focusable: false,
      style: {
        stroke: EDGE_COLOR[e.state],
        strokeWidth: e.state === 'live' || e.state === 'waiting' ? 2 : 1.5,
        strokeDasharray: e.state === 'pending' ? '4 4' : undefined,
      },
      markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLOR[e.state], width: 14, height: 14 },
    }));
    for (const r of redos) {
      edges.push({
        id: r.id,
        source: r.source,
        target: r.target,
        sourceHandle: 'top-out',
        targetHandle: 'top-redo',
        type: 'smoothstep',
        focusable: false,
        label: `redo ×${r.count}`,
        labelStyle: { fill: color('warning'), fontSize: 11, fontWeight: 600 },
        labelBgStyle: { fill: color('surface') },
        labelBgPadding: [6, 3],
        labelBgBorderRadius: 6,
        style: { stroke: color('warning', 0.8), strokeWidth: 1.5, strokeDasharray: '6 4' },
        markerEnd: { type: MarkerType.ArrowClosed, color: color('warning', 0.8), width: 14, height: 14 },
      });
    }
    return { nodes, edges };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, onSelect, onReview]);

  // Refit when the card resizes (sidebar collapse, window resize).
  const wrap = useRef<HTMLDivElement>(null);
  const flow = useRef<ReactFlowInstance | null>(null);
  useEffect(() => {
    const el = wrap.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => flow.current?.fitView({ padding: 0.06 }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={wrap} className="h-[25rem] w-full" role="group" aria-label="Audit pipeline graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onInit={(inst) => {
          flow.current = inst;
          inst.fitView({ padding: 0.06 });
        }}
        fitView
        fitViewOptions={{ padding: 0.06 }}
        minZoom={0.3}
        maxZoom={1.1}
        nodesDraggable={false}
        nodesConnectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        panOnScroll={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
      />
    </div>
  );
}
