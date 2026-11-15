import { Boxes, Database, FileStack, Globe, MessagesSquare, Plug, type LucideIcon } from 'lucide-react';
import type { PluginCard } from './types';

/** Icon per plugin access type (plugin.yaml `access.type`). */
export const ACCESS_ICON: Record<string, LucideIcon> = {
  mlflow_model: Boxes,
  rest: Globe,
  llm_chat: MessagesSquare,
  batch_file: FileStack,
  dataset_only: Database,
};

export function accessIcon(type?: string): LucideIcon {
  return ACCESS_ICON[type ?? ''] ?? Plug;
}

const HUMAN_STAGE = /ui|human|review/i;

/** One stage next to a plugin in the pipeline (a plugin, a human step or an external system). */
export interface StageRef {
  id: string;
  label: string;
  human: boolean;
}

function shortId(id: string): string {
  return id.includes('.') ? id.split('.').slice(1).join('.') : id;
}

function humanize(slug: string): string {
  const words = slug.replace(/[-_]+/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Readable name for a stage id like `SYS-001.recruiter-ui`. */
export function stageRef(id: string, plugins: PluginCard[]): StageRef {
  const p = plugins.find((x) => x.id === id);
  const short = shortId(id);
  if (p) return { id, label: p.name, human: false };
  const human = HUMAN_STAGE.test(short);
  return {
    id,
    label: human ? humanize(short.replace(/[-_]?ui$/i, '')) || 'Human review' : humanize(short),
    human,
  };
}

/** The model or endpoint as a short chip: `sys-001-cv-ranker@champion`, `/v1/models/x/predict`. */
export function targetLabel(access: PluginCard['access']): { short: string; full: string } | null {
  if (access.uri) return { short: access.uri.replace(/^models:\//, ''), full: access.uri };
  if (access.url) {
    const full = access.method ? `${access.method} ${access.url}` : access.url;
    try {
      const u = new URL(access.url);
      return { short: `${u.host}${u.pathname}`, full };
    } catch {
      return { short: access.url, full };
    }
  }
  return null;
}

/** "Step 2 of 3" from `placement.position`, or the placement kind in words. */
export function placementLabel(placement: PluginCard['placement'] | undefined): string {
  if (!placement) return 'Standalone';
  if (placement.position) return `Step ${placement.position}`;
  return humanize(placement.kind ?? 'standalone');
}

const OUTPUT_LABEL: Record<string, string> = {
  binary_classification: 'Yes / no + score',
  multiclass_classification: 'Class + scores',
  regression: 'Number',
  table: 'Table',
  text: 'Text',
  chat: 'Chat reply',
};

/** Plain-language output, from `io.output.type`. */
export function outputLabel(io: PluginCard['io']): string | null {
  const type = io?.output?.type;
  if (typeof type !== 'string') return null;
  return OUTPUT_LABEL[type] ?? humanize(type);
}

export interface PluginFact {
  value: string;
  unit?: string;
  label: string;
}

function compact(n: number): string {
  return n >= 1000 ? `${Math.round(n / 100) / 10}k`.replace('.0k', 'k') : String(n);
}

/** The limits worth a glance, as big-number facts. */
export function limitFacts(limits?: Record<string, number>): PluginFact[] {
  if (!limits) return [];
  const out: PluginFact[] = [];
  if (limits.rps != null) out.push({ value: compact(limits.rps), unit: '/s', label: 'Rate limit' });
  if (limits.timeout_s != null) out.push({ value: compact(limits.timeout_s), unit: 's', label: 'Timeout' });
  if (limits.max_requests != null) out.push({ value: compact(limits.max_requests), label: 'Request budget' });
  for (const [k, v] of Object.entries(limits)) {
    if (!['rps', 'timeout_s', 'max_requests'].includes(k))
      out.push({ value: compact(v), label: humanize(k) });
  }
  return out;
}

/** Humanized label for a scenario hint / policy value. */
export function hintLabel(v: string): string {
  return humanize(v);
}
