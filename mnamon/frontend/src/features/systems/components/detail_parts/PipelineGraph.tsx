import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import { Building2, Plus, User } from 'lucide-react';
import { useMemo } from 'react';
import { cn } from '@/shared/lib/utils';
import { accessIcon } from '../../lib/plugins';
import { ACCESS_LABEL } from '../../lib/styles';
import type { GraphComponent, PluginGraph } from '../../lib/types';

type StageData = {
  component: GraphComponent;
  sub: string;
  accessType?: string;
  selected: boolean;
  clickable: boolean;
};

const HUMAN = /human|review|ui$/i;

function StageNode({ data }: NodeProps<Node<StageData>>) {
  const c = data.component;
  const human = !c.testable && HUMAN.test(`${c.kind} ${c.id}`);
  const Icon = c.testable ? accessIcon(data.accessType ?? 'mlflow_model') : human ? User : Building2;
  return (
    <div
      className={cn(
        'group relative flex w-56 items-center gap-3 rounded-xl border bg-surface px-3 py-2.5 shadow-card transition-[border-color,box-shadow] duration-150',
        data.clickable && 'cursor-pointer hover:border-primary/50 hover:shadow-pop',
        c.testable && !c.configured && 'border-dashed border-primary/40',
        !c.testable && 'border-border bg-surface-muted/40',
        c.configured && 'border-border',
        data.selected && 'border-primary/70 ring-2 ring-primary/25',
      )}
    >
      <Handle type="target" position={Position.Left} className="!border-border !bg-surface" />
      <div
        className={cn(
          'grid size-9 shrink-0 place-items-center rounded-lg [&_svg]:size-4',
          c.testable ? 'bg-primary/10 text-primary' : 'bg-surface-muted text-muted',
        )}
      >
        <Icon />
      </div>
      <div className="min-w-0 flex-1">
        <div className={cn('truncate text-sm font-semibold leading-tight', !c.testable && 'text-muted')}>
          {c.name}
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 truncate text-2xs text-muted">
          {c.testable && (
            <span
              aria-hidden
              className={cn('size-1.5 shrink-0 rounded-full', c.configured ? 'bg-success' : 'bg-warning')}
            />
          )}
          <span className="truncate">{data.sub}</span>
        </div>
      </div>
      {c.testable && !c.configured && (
        <span className="grid size-6 shrink-0 place-items-center rounded-md bg-primary/10 text-primary [&_svg]:size-3.5">
          <Plus />
        </span>
      )}
      <Handle type="source" position={Position.Right} className="!border-border !bg-surface" />
    </div>
  );
}

const nodeTypes = { stage: StageNode };

function subtitle(c: GraphComponent, accessType?: string): string {
  if (c.testable) {
    if (!c.configured) return 'No plugin yet · click to set up';
    return ACCESS_LABEL[accessType ?? ''] ?? 'Plugin ready';
  }
  if (HUMAN.test(`${c.kind} ${c.id}`)) return 'Human step · not testable';
  return 'Upstream system · not testable';
}

/**
 * The system as a graph (architecture.yaml): one box per component, models are clickable and
 * open their plugin. A model without a plugin has a dashed border and a "+".
 */
export function PipelineGraph({
  graph,
  selected,
  onSelect,
}: {
  graph: PluginGraph;
  selected?: string;
  onSelect?: (component: GraphComponent) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const ids = graph.components.map((c) => c.id);
    const links = graph.edges
      .map((e) => [e.source, e.target] as const)
      .filter(([a, b]) => ids.includes(a) && ids.includes(b));
    // Longest-path layering, left to right.
    const level = new Map<string, number>(ids.map((i) => [i, 0]));
    for (let pass = 0; pass < ids.length; pass++) {
      for (const [a, b] of links) level.set(b, Math.max(level.get(b)!, level.get(a)! + 1));
    }
    const perLevel = new Map<number, number>();
    const nodes: Node<StageData>[] = graph.components.map((c) => {
      const l = level.get(c.id)!;
      const row = perLevel.get(l) ?? 0;
      perLevel.set(l, row + 1);
      const accessType = c.plugin ? graph.plugins[c.plugin]?.access?.type : undefined;
      return {
        id: c.id,
        type: 'stage',
        position: { x: l * 290, y: row * 96 },
        data: {
          component: c,
          accessType,
          sub: subtitle(c, accessType),
          selected: c.id === selected,
          clickable: !!onSelect,
        },
        draggable: false,
      };
    });
    const edges: Edge[] = links.map(([a, b]) => ({
      id: `${a}>${b}`,
      source: a,
      target: b,
      animated: a === selected || b === selected,
      markerEnd: { type: MarkerType.ArrowClosed },
    }));
    return { nodes, edges };
  }, [graph, selected, onSelect]);

  return (
    <div className="h-64 overflow-hidden rounded-xl border border-border bg-surface-muted/30">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => {
          onSelect?.((node.data as StageData).component);
        }}
        fitView
        fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }}
        nodesConnectable={false}
        nodesDraggable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
        minZoom={0.4}
        maxZoom={1.5}
      >
        <Background gap={18} size={1} />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
    </div>
  );
}
