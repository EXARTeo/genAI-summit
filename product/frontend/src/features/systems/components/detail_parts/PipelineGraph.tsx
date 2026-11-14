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
import { Cpu, User } from 'lucide-react';
import { useMemo } from 'react';
import { cn } from '@/shared/lib/utils';
import type { PluginCard } from '../../lib/types';

type StageData = { label: string; sub: string; human: boolean; highlighted: boolean };

function StageNode({ data }: NodeProps<Node<StageData>>) {
  return (
    <div
      className={cn(
        'flex w-48 items-center gap-2.5 rounded-lg border bg-surface px-3 py-2.5 shadow-card',
        data.highlighted ? 'border-primary/60 ring-1 ring-primary/30' : 'border-border',
      )}
    >
      <Handle type="target" position={Position.Left} className="!border-border !bg-surface" />
      <div
        className={cn(
          'grid size-8 shrink-0 place-items-center rounded-lg',
          data.human ? 'bg-surface-muted text-text' : 'bg-surface-muted text-muted',
        )}
      >
        {data.human ? <User className="size-4" /> : <Cpu className="size-4" />}
      </div>
      <div className="min-w-0">
        <div className="truncate text-xs font-semibold">{data.label}</div>
        <div className="truncate font-mono text-2xs text-muted">{data.sub}</div>
      </div>
      <Handle type="source" position={Position.Right} className="!border-border !bg-surface" />
    </div>
  );
}

const nodeTypes = { stage: StageNode };

/**
 * Pipeline placement of every plugin, derived from `placement.upstream/downstream`.
 * `highlight` = the plugin id whose card is selected.
 */
export function PipelineGraph({ plugins, highlight }: { plugins: PluginCard[]; highlight?: string }) {
  const { nodes, edges } = useMemo(() => {
    const ids = new Set<string>();
    const links: [string, string][] = [];
    for (const p of plugins) {
      ids.add(p.id);
      for (const u of p.placement?.upstream ?? []) {
        ids.add(u);
        links.push([u, p.id]);
      }
      for (const d of p.placement?.downstream ?? []) {
        ids.add(d);
        links.push([p.id, d]);
      }
    }
    // Longest-path layering, left to right.
    const level = new Map<string, number>([...ids].map((i) => [i, 0]));
    for (let pass = 0; pass < ids.size; pass++) {
      for (const [a, b] of links) level.set(b, Math.max(level.get(b)!, level.get(a)! + 1));
    }
    const perLevel = new Map<number, number>();
    const byId = new Map(plugins.map((p) => [p.id, p]));
    const nodes: Node<StageData>[] = [...ids].map((id) => {
      const l = level.get(id)!;
      const row = perLevel.get(l) ?? 0;
      perLevel.set(l, row + 1);
      const p = byId.get(id);
      const short = id.includes('.') ? id.split('.').slice(1).join('.') : id;
      return {
        id,
        type: 'stage',
        position: { x: l * 250, y: row * 90 },
        data: {
          label: p?.name ?? short.replace(/-/g, ' '),
          sub: p ? p.access.type : /ui|human|review/i.test(short) ? 'human review' : 'external',
          human: !p && /ui|human|review/i.test(short),
          highlighted: id === highlight,
        },
        draggable: false,
      };
    });
    const seen = new Set<string>();
    const edges: Edge[] = links
      .filter(([a, b]) => !seen.has(`${a}>${b}`) && seen.add(`${a}>${b}`))
      .map(([a, b]) => ({
        id: `${a}>${b}`,
        source: a,
        target: b,
        animated: a === highlight || b === highlight,
        markerEnd: { type: MarkerType.ArrowClosed },
      }));
    return { nodes, edges };
  }, [plugins, highlight]);

  return (
    <div className="h-64 overflow-hidden rounded-xl border border-border bg-surface-muted/30">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        nodesConnectable={false}
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
