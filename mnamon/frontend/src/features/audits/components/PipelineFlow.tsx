import '@/styles/audit-flow.css';
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
  Panel,
  EdgeLabelRenderer,
  ReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
} from '@xyflow/react';
import { useReducedMotion } from 'framer-motion';
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { cn } from '@/shared/lib/utils';
import { GRAPH, PHASES, graphLayout, graphModel } from '../lib/graph';
import { STAGES, type StageDef, type StepState } from '../lib/pipeline';
import { stepSummary } from '../lib/stepMeta';
import type { AuditDetail } from '../lib/types';
import { GraphNode } from './pipeline_parts/GraphNode';

// The audit run as an agent graph on a canvas that fills its parent: one band per phase, a row of nodes flowing left to right,
// the run wrapping from the end of a phase into the next. The step that runs now wears
// mAgenticX's sub-agent running light, and particles flow along the edge into it; a gate that
// waits for a person does the same in amber. Redo loops arc back over the row. Drawn at
// zoom 1 so text is its real size; drag to pan, Ctrl + scroll or pinch to zoom, the controls fit it back.
// Click a node (or Enter on a focused one) to open the step in the side panel.

type StepData = {
  stage: StageDef;
  state: StepState;
  summary?: string;
  selected: boolean;
  onReview: () => void;
};
type GroupData = {
  index: number;
  label: string;
  done: number;
  total: number;
  tone: 'live' | 'waiting' | 'done' | 'idle';
  width: number;
  height: number;
};
type EdgeTone = 'done' | 'live' | 'waiting' | 'pending' | 'redo';
type FlowEdgeData = {
  tone: EdgeTone;
  kind: 'row' | 'wrap' | 'redo';
  midY?: number;
  label?: string;
  motion: boolean;
};

const STATE_WORD: Record<StepState, string> = {
  done: 'done',
  active: 'running now',
  pending: 'not started',
  blocked: 'failed',
  'needs-approval': 'waiting for your decision',
};

function StepNode({ data }: NodeProps<Node<StepData>>) {
  return (
    <GraphNode
      stage={data.stage}
      state={data.state}
      summary={data.summary}
      selected={data.selected}
      onReview={data.onReview}
    />
  );
}

function GroupNode({ data }: NodeProps<Node<GroupData>>) {
  return (
    <div className="pg-group" data-tone={data.tone} style={{ width: data.width, height: data.height }}>
      <div className="flex items-center gap-2.5 px-4" style={{ height: GRAPH.header - 4 }}>
        <span className="pg-group-index num grid size-5 place-items-center rounded-md text-[11px] font-semibold">
          {data.index}
        </span>
        <span className="text-[13px] font-semibold tracking-tight text-text">{data.label}</span>
        <span className="num ml-auto text-xs font-medium text-muted">
          {data.done}/{data.total}
        </span>
      </div>
    </div>
  );
}

const R = 12;

/** Row: straight into the next node. Wrap: right, down between bands, left, into the next phase. Redo: an arc back over the row. */
function FlowEdge({ id, sourceX, sourceY, targetX, targetY, data }: EdgeProps<Edge<FlowEdgeData>>) {
  const tone = data?.tone ?? 'pending';
  const kind = data?.kind ?? 'row';
  let path: string;
  let arrow: string;
  let mid = { x: 0, y: 0 };
  if (kind === 'redo') {
    // Low enough that the apex label stays inside the band header (never above the canvas).
    const h = 30;
    path = `M ${sourceX},${sourceY} C ${sourceX},${sourceY - h} ${targetX},${targetY - h} ${targetX},${targetY}`;
    arrow = `M ${targetX - 3.5},${targetY - 7} L ${targetX},${targetY} L ${targetX + 3.5},${targetY - 7} Z`;
    mid = { x: (sourceX + targetX) / 2, y: sourceY - h * 0.75 };
  } else if (kind === 'wrap') {
    const xr = sourceX + 22;
    const xl = targetX - 22;
    const my = data?.midY ?? (sourceY + targetY) / 2;
    path = [
      `M ${sourceX},${sourceY}`,
      `H ${xr - R}`,
      `Q ${xr},${sourceY} ${xr},${sourceY + R}`,
      `V ${my - R}`,
      `Q ${xr},${my} ${xr - R},${my}`,
      `H ${xl + R}`,
      `Q ${xl},${my} ${xl},${my + R}`,
      `V ${targetY - R}`,
      `Q ${xl},${targetY} ${xl + R},${targetY}`,
      `H ${targetX}`,
    ].join(' ');
    arrow = `M ${targetX - 7},${targetY - 3.5} L ${targetX},${targetY} L ${targetX - 7},${targetY + 3.5} Z`;
  } else {
    path = `M ${sourceX},${sourceY} L ${targetX},${targetY}`;
    arrow = `M ${targetX - 7},${targetY - 3.5} L ${targetX},${targetY} L ${targetX - 7},${targetY + 3.5} Z`;
  }
  const flowing = (tone === 'live' || tone === 'waiting') && data?.motion;
  return (
    <>
      <g className={cn('pg-edge', `is-${tone}`)}>
        {(tone === 'live' || tone === 'waiting') && <path d={path} className="pg-edge-glow" fill="none" />}
        <BaseEdge id={id} path={path} />
        <path d={arrow} className="pg-edge-arrow" aria-hidden />
        {flowing &&
          [0, 0.45, 0.9].map((begin) => (
            <circle key={begin} r={2.6} className="pg-particle">
              <animateMotion dur="1.35s" begin={`${begin}s`} repeatCount="indefinite" path={path} />
            </circle>
          ))}
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

const nodeTypes = { step: StepNode, phase: GroupNode };

/** Canvas margin round the graph, room kept for the legend, and the widest the graph lays out (px). */
const CANVAS_PAD = 28;
const LEGEND_H = 52;
const REST_MIN_ZOOM = 0.85;
const MAX_GRAPH_W = 1240;
const edgeTypes = { flow: FlowEdge };

function Legend() {
  return (
    <div className="pg-legend flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-xl px-3 py-2 text-[11.5px] text-muted">
      <span className="flex items-center gap-1.5">
        <span className="size-3 rounded-[4px] border border-primary/50 bg-primary/10" /> Agent step
      </span>
      <span className="flex items-center gap-1.5">
        <span className="size-3 rounded-full border border-warning/60 bg-warning/10" /> Human gate
      </span>
      <span className="flex items-center gap-1.5">
        <span className="pg-legend-live size-3 rounded-[4px]" /> Working now
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-0.5 w-5 rounded-full bg-primary/70" /> Done
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-0 w-5 border-t-[1.5px] border-dashed border-muted/60" /> Next
      </span>
      <span className="hidden border-l border-border pl-4 xl:inline">
        Drag to move · Ctrl + scroll to zoom
      </span>
    </div>
  );
}

export interface PipelineFlowProps {
  audit: AuditDetail;
  selected: string;
  onSelect: (stageId: string) => void;
  onReview: () => void;
  /** Width (px) of a side panel covering the right of the screen: the graph slides so the selected node stays in view. */
  coveredRight?: number;
  /** Height (px) of chrome floating over the top of the canvas (the page title): the resting view starts below it. */
  insetTop?: number;
}

export function PipelineFlow({
  audit,
  selected,
  onSelect,
  onReview,
  coveredRight = 0,
  insetTop = 0,
}: PipelineFlowProps) {
  const reduced = !!useReducedMotion();
  const wrap = useRef<HTMLDivElement>(null);
  const flow = useRef<ReactFlowInstance | null>(null);
  // Set once React Flow is up; the viewport effect below re-runs then (onInit only sees the
  // first render's numbers, measured before the canvas had its final size).
  const [ready, setReady] = useState(false);
  const placed = useRef(false);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const measure = () => setSize({ width: el.clientWidth, height: el.clientHeight });
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const { width, height } = size;

  const { states, edges: pe, redos } = graphModel(audit);
  // The graph keeps a margin inside the canvas and stops growing on very wide screens.
  const layout = graphLayout(
    Math.min(Math.max(width - CANVAS_PAD * 2, 0), MAX_GRAPH_W) || 1000,
    (id) => states[id] === 'needs-approval',
  );
  // Resting view: centred and scaled to fit, but never below REST_MIN_ZOOM (text stays readable);
  // when the graph is still taller than the canvas, scroll it so the current step's row shows.
  const live = STAGES.find((s) => states[s.id] === 'active' || states[s.id] === 'needs-approval')?.id;
  const focus = layout.positions[live ?? selected];
  const focusBottom = focus ? focus.y + focus.height : 0;
  const rest = useMemo(() => {
    // The band the graph may use: below the floating title, above the legend.
    const top = insetTop || CANVAS_PAD * 0.75;
    const avail = height - LEGEND_H - top;
    const fit = Math.min(
      1,
      (avail - CANVAS_PAD / 2) / layout.height,
      (width - CANVAS_PAD * 2) / layout.width,
    );
    const zoom = Math.max(fit, REST_MIN_ZOOM);
    const x = (width - layout.width * zoom) / 2;
    if (layout.height * zoom <= avail) {
      return { x, y: top + (avail - layout.height * zoom) / 2, zoom };
    }
    const overflow = focusBottom * zoom - (avail - CANVAS_PAD / 2);
    return { x, y: top - Math.max(0, overflow), zoom };
  }, [width, height, layout.width, layout.height, focusBottom, insetTop]);
  const stateKey = Object.values(states).join();
  const summaries = useMemo(
    () => Object.fromEntries(STAGES.map((s) => [s.id, stepSummary(s.id, audit)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [audit.updatedAt, audit.artifacts.length, audit.approvals.length],
  );

  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = [
      ...PHASES.map((p, i) => {
        const g = layout.groups[i];
        const st = p.stages.map((s) => states[s]);
        const done = st.filter((s) => s === 'done').length;
        const tone: GroupData['tone'] = st.includes('active')
          ? 'live'
          : st.includes('needs-approval')
            ? 'waiting'
            : done === p.stages.length
              ? 'done'
              : 'idle';
        return {
          id: `phase-${p.id}`,
          type: 'phase',
          position: { x: 0, y: g.y },
          data: {
            index: i + 1,
            label: p.label,
            done,
            total: p.stages.length,
            tone,
            width: layout.width,
            height: g.height,
          } satisfies GroupData,
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
          style: { width: layout.colWidth, height: pos.height, ['--pg-delay' as string]: `${i * 45}ms` },
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
    const edges: Edge[] = pe.map((e) => {
      const next = layout.groups[PHASES.findIndex((p) => p.stages.includes(e.target))];
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: 'r',
        targetHandle: 'l',
        type: 'flow',
        zIndex: 1,
        data: {
          tone: e.state,
          kind: e.wrap ? 'wrap' : 'row',
          midY: e.wrap ? next.y - GRAPH.groupGap / 2 : undefined,
          motion: !reduced,
        } satisfies FlowEdgeData,
      };
    });
    for (const r of redos) {
      edges.push({
        id: r.id,
        source: r.source,
        target: r.target,
        sourceHandle: 't-out',
        targetHandle: 't-in',
        type: 'flow',
        zIndex: 1,
        data: { tone: 'redo', kind: 'redo', label: `redo ×${r.count}`, motion: false } satisfies FlowEdgeData,
      });
    }
    return { nodes, edges };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout.width, stateKey, selected, summaries, redos.map((r) => r.count).join(), reduced, onReview]);

  // With a side panel open, centre the selected node in the part of the canvas still visible;
  // slide back to the resting view when it closes.
  const sel = layout.positions[selected];
  const hasSel = !!sel;
  const selX = sel ? sel.x + layout.colWidth / 2 : 0;
  useEffect(() => {
    const rf = flow.current;
    const el = wrap.current;
    if (!rf || !el) return;
    // The first placement snaps; later moves (panel open/close, the live step advancing) glide.
    const duration = reduced || !placed.current ? 0 : 450;
    placed.current = true;
    if (!coveredRight || !hasSel) {
      void rf.setViewport(rest, { duration });
      return;
    }
    const rect = el.getBoundingClientRect();
    const visibleRight = Math.min(rect.right, window.innerWidth - coveredRight);
    // Step back a little so more of the graph fits beside the panel.
    const zoom = Math.min(0.85, rest.zoom);
    const centre = (Math.max(visibleRight, rect.left + 160) - rect.left) / 2;
    void rf.setViewport({ x: centre - selX * zoom, y: rest.y, zoom }, { duration });
  }, [ready, coveredRight, selected, selX, reduced, hasSel, rest]);

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const target = e.target as HTMLElement;
    if (!target.classList?.contains('react-flow__node')) return;
    const id = target.getAttribute('data-id');
    if (!id || id.startsWith('phase-')) return;
    e.preventDefault();
    onSelect(id);
  };

  return (
    <div
      ref={wrap}
      className="size-full"
      role="group"
      aria-label="Audit pipeline: three phases, each ending at a human gate"
      onKeyDown={onKeyDown}
    >
      {width > 0 && height > 0 && (
        <ReactFlow
          className="audit-flow"
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onInit={(rf) => {
            flow.current = rf;
            setReady(true);
          }}
          onNodeClick={(_, n) => n.type === 'step' && onSelect(n.id)}
          defaultViewport={rest}
          minZoom={0.45}
          maxZoom={1.6}
          translateExtent={[
            [-width, -height],
            [layout.width + width, layout.height + height],
          ]}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          nodesFocusable
          edgesFocusable={false}
          panOnDrag
          panOnScroll={false}
          zoomOnScroll={false}
          zoomOnPinch
          zoomOnDoubleClick={false}
          preventScrolling={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} />
          <Panel position="bottom-left">
            <Legend />
          </Panel>
          <Controls
            position="bottom-right"
            showInteractive={false}
            fitViewOptions={{ padding: 0.08, maxZoom: 1, duration: 300 }}
            className="pg-controls"
          />
        </ReactFlow>
      )}
    </div>
  );
}
