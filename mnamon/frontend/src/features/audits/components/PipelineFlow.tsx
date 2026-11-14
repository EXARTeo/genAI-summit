import '@/styles/audit-flow.css';
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  EdgeLabelRenderer,
  Handle,
  Position,
  ReactFlow,
  getBezierPath,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import { useReducedMotion } from 'framer-motion';
import { ChevronRight } from 'lucide-react';
import { useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { cn } from '@/shared/lib/utils';
import { LANE, PHASES, graphModel, laneLayout } from '../lib/graph';
import { STAGES, type StageDef, type StepState } from '../lib/pipeline';
import { stepSummary } from '../lib/stepMeta';
import type { AuditDetail } from '../lib/types';
import { STEP_CARD_ACTION_H, STEP_CARD_H, StepCard } from './pipeline_parts/StepCard';

// The audit run's pipeline graph, ported from mAgenticX's workflow run view (WorkflowGraph /
// WorkflowNodeCard / WorkflowEdge): the same card, edge and status language, on our brand
// tokens. Our flow is a fixed 14-step pipeline in three phases, so instead of a free-zoom
// left-to-right canvas it is laid out as three lanes that fill the card, drawn at zoom 1 so
// the text is its real size; each lane ends at a human gate and hands over to the next.
// Click a card (or Enter on a focused one) to open the step below.

type StepData = {
  stage: StageDef;
  state: StepState;
  summary?: string;
  selected: boolean;
  onReview: () => void;
};
type LaneData = {
  label: string;
  done: number;
  total: number;
  last: boolean;
  handoff: boolean;
  width: number;
  height: number;
};
type EdgeTone = 'done' | 'live' | 'waiting' | 'pending' | 'redo';
type AuditEdgeData = { tone: EdgeTone; label?: string };

const handle = 'audit-handle';
const STATE_WORD: Record<StepState, string> = {
  done: 'done',
  active: 'running',
  pending: 'not started',
  blocked: 'failed',
  'needs-approval': 'waiting for your decision',
};

function StepNode({ data }: NodeProps<Node<StepData>>) {
  return (
    <>
      <Handle type="target" position={Position.Top} id="t" className={handle} />
      <Handle type="source" position={Position.Bottom} id="b" className={handle} />
      <Handle
        type="source"
        position={Position.Right}
        id="r-out"
        style={{ top: STEP_CARD_H / 2 }}
        className={handle}
      />
      <Handle
        type="target"
        position={Position.Right}
        id="r-in"
        style={{ top: STEP_CARD_H / 2 }}
        className={handle}
      />
      <StepCard
        stage={data.stage}
        state={data.state}
        summary={data.summary}
        selected={data.selected}
        onReview={data.onReview}
      />
    </>
  );
}

function LaneNode({ data }: NodeProps<Node<LaneData>>) {
  const complete = data.done === data.total;
  return (
    <div className="audit-lane relative rounded-2xl" style={{ width: data.width, height: data.height }}>
      <div className="flex items-center justify-between px-4" style={{ height: LANE.header - 8 }}>
        <span className="text-[13.5px] font-semibold tracking-tight text-text">{data.label}</span>
        <span
          className={cn(
            'num rounded-full px-2 py-0.5 text-xs font-medium',
            complete ? 'bg-success/12 text-success' : 'bg-surface-sunken text-muted',
          )}
        >
          {data.done}/{data.total}
        </span>
      </div>
      {!data.last && (
        <span
          aria-hidden
          className={cn(
            'absolute grid size-7 place-items-center rounded-full border bg-surface shadow-sm',
            data.handoff ? 'border-primary/50 text-primary' : 'border-border text-muted',
          )}
          style={{ right: -LANE.gutter / 2 - 14, top: (LANE.header - 8) / 2 - 14 }}
        >
          <ChevronRight className="size-4" />
        </span>
      )}
    </div>
  );
}

/** Edge: a short bezier down the lane with one small arrowhead; a redo loops back on the right. */
function AuditEdge({ id, sourceX, sourceY, targetX, targetY, data }: EdgeProps<Edge<AuditEdgeData>>) {
  const tone = data?.tone ?? 'pending';
  let path: string;
  let arrow: string;
  let mid = { x: 0, y: 0 };
  if (tone === 'redo') {
    const swing = LANE.pad + 18;
    path = `M ${sourceX},${sourceY} C ${sourceX + swing},${sourceY} ${targetX + swing},${targetY} ${targetX},${targetY}`;
    arrow = `M ${targetX + 7},${targetY - 3.5} L ${targetX},${targetY} L ${targetX + 7},${targetY + 3.5} Z`;
    mid = { x: Math.max(sourceX, targetX) + swing * 0.75, y: (sourceY + targetY) / 2 };
  } else {
    [path] = getBezierPath({
      sourceX,
      sourceY,
      sourcePosition: Position.Bottom,
      targetX,
      targetY,
      targetPosition: Position.Top,
    });
    arrow = `M ${targetX - 3.5},${targetY - 7} L ${targetX},${targetY} L ${targetX + 3.5},${targetY - 7} Z`;
  }
  return (
    <>
      <g className={cn('audit-edge', `is-${tone}`)}>
        {(tone === 'live' || tone === 'waiting') && <path d={path} className="audit-edge-glow" fill="none" />}
        <BaseEdge id={id} path={path} />
        <path d={arrow} className="audit-edge-arrow" aria-hidden />
      </g>
      {data?.label && (
        <EdgeLabelRenderer>
          <span
            className="absolute rounded-full border border-warning/40 bg-surface px-2 py-0.5 text-[11px] font-semibold text-warning shadow-sm"
            style={{ transform: `translate(-50%, -50%) translate(${mid.x}px, ${mid.y}px)` }}
          >
            {data.label}
          </span>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const nodeTypes = { step: StepNode, lane: LaneNode };
const edgeTypes = { audit: AuditEdge };

export interface PipelineFlowProps {
  audit: AuditDetail;
  selected: string;
  onSelect: (stageId: string) => void;
  onReview: () => void;
}

export function PipelineFlow({ audit, selected, onSelect, onReview }: PipelineFlowProps) {
  const reduced = !!useReducedMotion();
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    setWidth(el.clientWidth);
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { states, edges: pe, redos } = graphModel(audit);
  const heightOf = (id: string) =>
    states[id] === 'needs-approval' ? STEP_CARD_H + STEP_CARD_ACTION_H : STEP_CARD_H;
  const layout = laneLayout(width || 1100, heightOf);
  const stateKey = Object.values(states).join();
  const summaries = useMemo(
    () => Object.fromEntries(STAGES.map((s) => [s.id, stepSummary(s.id, audit)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [audit.updatedAt, audit.artifacts.length, audit.approvals.length],
  );

  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = [
      ...PHASES.map((p, i) => {
        const done = p.stages.filter((s) => states[s] === 'done').length;
        return {
          id: `lane-${p.id}`,
          type: 'lane',
          position: { x: layout.lanes[i].x, y: 0 },
          data: {
            label: p.label,
            done,
            total: p.stages.length,
            last: i === PHASES.length - 1,
            handoff: done === p.stages.length,
            width: layout.laneWidth,
            height: layout.height,
          } satisfies LaneData,
          selectable: false,
          focusable: false,
          draggable: false,
          zIndex: 0,
        };
      }),
      ...STAGES.map((s, i) => {
        const pos = layout.positions[s.id];
        return {
          id: s.id,
          type: 'step',
          ariaLabel: `Step ${i + 1}: ${s.label}${s.gate ? ' (human gate)' : ''}, ${STATE_WORD[states[s.id]]}. Press Enter to open.`,
          position: { x: pos.x, y: pos.y },
          style: { width: layout.cardWidth, height: pos.height },
          data: {
            stage: s,
            state: states[s.id],
            summary: summaries[s.id],
            selected: s.id === selected,
            onReview,
          } satisfies StepData,
          draggable: false,
          zIndex: 2,
        };
      }),
    ];
    const edges: Edge[] = pe
      .filter((e) => !e.wrap)
      .map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: 'b',
        targetHandle: 't',
        type: 'audit',
        zIndex: 1,
        data: {
          tone: reduced && e.state !== 'done' && e.state !== 'pending' ? 'done' : e.state,
        } satisfies AuditEdgeData,
      }));
    for (const r of redos) {
      edges.push({
        id: r.id,
        source: r.source,
        target: r.target,
        sourceHandle: 'r-out',
        targetHandle: 'r-in',
        type: 'audit',
        zIndex: 1,
        data: { tone: 'redo', label: `redo ×${r.count}` } satisfies AuditEdgeData,
      });
    }
    return { nodes, edges };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [width, stateKey, selected, summaries, redos.map((r) => r.count).join(), reduced, onReview]);

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const target = e.target as HTMLElement;
    if (!target.classList?.contains('react-flow__node')) return;
    const id = target.getAttribute('data-id');
    if (!id || id.startsWith('lane-')) return;
    e.preventDefault();
    onSelect(id);
  };

  return (
    <div
      ref={wrap}
      className="w-full"
      style={{ height: layout.height + 2 }}
      role="group"
      aria-label="Audit pipeline: three phases, each ending at a human gate"
      onKeyDown={onKeyDown}
    >
      {width > 0 && (
        <ReactFlow
          className="audit-flow"
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodeClick={(_, n) => n.type === 'step' && onSelect(n.id)}
          defaultViewport={{ x: 0, y: 0, zoom: 1 }}
          minZoom={1}
          maxZoom={1}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          nodesFocusable
          edgesFocusable={false}
          panOnDrag={false}
          panOnScroll={false}
          zoomOnScroll={false}
          zoomOnPinch={false}
          zoomOnDoubleClick={false}
          preventScrolling={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} />
        </ReactFlow>
      )}
    </div>
  );
}
