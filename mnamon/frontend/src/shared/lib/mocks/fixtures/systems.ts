/**
 * In-memory system folders for mock mode, seeded from the real seed cases
 * (seed-cases.json, regenerate with `npm run fixtures`). Writes create new
 * versions, like the backend's append-only workspace files.
 */
import { parse } from 'yaml';
import type { FileEvent, System, SystemCard, WorkspaceFile } from '@/features/systems/lib/types';
import seed from './seed-cases.json';
import { mockTime } from '../time';

const SEED = seed as Record<string, Record<string, string>>;
const SEEDED_AT = mockTime('2026-11-14T09:00:00Z');

interface StoredVersion extends WorkspaceFile {
  text: string;
}

/** Demo state for the gallery: status + last audit per system. */
const DEMO: Record<string, Pick<SystemCard, 'last_audit'> & { status: string }> = {
  'SYS-001': {
    status: 'active',
    last_audit: {
      id: 'AUD-0007',
      status: 'awaiting_approval',
      at: mockTime('2026-11-14T10:42:00Z'),
      findings: { gaps: 3, supports: 4, inconclusive: 1 },
    },
  },
  'SYS-002': {
    status: 'active',
    last_audit: {
      id: 'AUD-0005',
      status: 'completed',
      at: mockTime('2026-11-13T16:05:00Z'),
      findings: { gaps: 0, supports: 7, inconclusive: 1 },
    },
  },
  'SYS-003': {
    status: 'active',
    last_audit: { id: 'AUD-0006', status: 'running', at: mockTime('2026-11-14T11:20:00Z') },
  },
};

function contentType(path: string): string {
  if (/\.ya?ml$/.test(path)) return 'application/yaml';
  if (/\.json$/.test(path)) return 'application/json';
  if (/\.csv$/.test(path)) return 'text/csv';
  if (/\.md$/.test(path)) return 'text/markdown';
  if (/\.pdf$/.test(path)) return 'application/pdf';
  return 'text/plain';
}

function fakeSha(s: string): string {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return (h >>> 0).toString(16).padStart(8, '0').repeat(8);
}

const files = new Map<string, StoredVersion[]>(); // `${systemId}:${path}` -> versions (oldest first)
const events: FileEvent[] = [];
const systems = new Map<string, System>();
let eventSeq = 1;

function key(systemId: string, path: string) {
  return `${systemId}:${path}`;
}

export function writeFile(
  systemId: string,
  path: string,
  text: string,
  actor = 'user:demo',
  reason: string | null = null,
  at = new Date().toISOString(),
): { file: WorkspaceFile; changed: boolean } {
  const k = key(systemId, path);
  const versions = files.get(k) ?? [];
  const cur = versions[versions.length - 1];
  if (cur && cur.text === text) return { file: strip(cur), changed: false };
  versions.forEach((v) => (v.isCurrent = false));
  const v: StoredVersion = {
    namespace: `system:${systemId}`,
    path,
    version: (cur?.version ?? 0) + 1,
    contentType: contentType(path),
    size: new TextEncoder().encode(text).length,
    sha256: fakeSha(text),
    createdBy: actor,
    isCurrent: true,
    data: {},
    createdAt: at,
    text,
  };
  versions.push(v);
  files.set(k, versions);
  events.unshift({
    id: eventSeq++,
    namespace: v.namespace,
    path,
    version: v.version,
    action: cur ? 'update' : 'create',
    actor,
    reason,
    auditId: null,
    runId: null,
    traceId: null,
    data: {},
    at,
  });
  return { file: strip(v), changed: true };
}

function strip(v: StoredVersion): WorkspaceFile {
  const { text: _text, ...rest } = v;
  return rest;
}

// ---- seed ----------------------------------------------------------------
for (const [id, folder] of Object.entries(SEED)) {
  for (const [path, text] of Object.entries(folder))
    writeFile(id, path, text, 'seed', 'seed import', SEEDED_AT);
  const card = (parse(folder['system-card.yaml'] ?? '') ?? {}) as SystemCard & { name?: string };
  const { name = id, ...data } = card;
  const demo = DEMO[id] ?? { status: 'active', last_audit: null };
  systems.set(id, {
    id,
    name,
    status: demo.status,
    data: { ...data, last_audit: demo.last_audit },
    createdAt: SEEDED_AT,
    updatedAt: demo.last_audit?.at ?? SEEDED_AT,
  });
}
// A second version of one file, so the version list has history to show.
{
  const p = 'plugins/cv-ranker/docs/known-issues.md';
  const cur = SEED['SYS-001']?.[p];
  if (cur) {
    writeFile(
      'SYS-001',
      p,
      `${cur}\n- Ranker returns 429 above 20 rps (seen during AUD-0007).\n`,
      'agent:audit',
      'quirk observed during a run',
      mockTime('2026-11-14T10:31:00Z'),
    );
  }
}

// ---- queries --------------------------------------------------------------
export const mockSystems = {
  list: () => [...systems.values()],
  get: (id: string) => systems.get(id),
  tree: (id: string, prefix?: string | null) =>
    [...files.entries()]
      .filter(([k]) => k.startsWith(`${id}:`))
      .map(([, v]) => strip(v[v.length - 1]))
      .filter((f) => !prefix || f.path.startsWith(prefix))
      .sort((a, b) => a.path.localeCompare(b.path)),
  read: (id: string, path: string, version?: number) => {
    const versions = files.get(key(id, path));
    if (!versions) return undefined;
    const v = version ? versions.find((x) => x.version === version) : versions[versions.length - 1];
    return v ? { ...strip(v), text: v.text, dataB64: null } : undefined;
  },
  versions: (id: string, path: string) => (files.get(key(id, path)) ?? []).map(strip).reverse(),
  events: (id: string) => events.filter((e) => e.namespace === `system:${id}`),
};
