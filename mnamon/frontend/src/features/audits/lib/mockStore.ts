// In-browser state for mock mode. A running audit advances one stage every few seconds
// (computed lazily on read) and stops at the next HITL gate, so the Stepper animates live.
// Seeded audits start frozen; approving a gate starts the clock.
// An approval moves the audit past its gate; a rejection keeps it there.
import { STAGES, stageIndex } from './pipeline';
import { buildMockAudits } from './mocks';
import type { Approval, ApprovalIn, ApprovalResult, AuditDetail } from './types';

const STEP_MS = 3500;

interface Live {
  audit: AuditDetail;
  /** Full artifact set the run will reveal as it reaches each stage. */
  pool: AuditDetail['artifacts'];
  runningSince: number | null;
  baseIndex: number;
}

let store: Map<string, Live> | null = null;

function init(): Map<string, Live> {
  const full = buildMockAudits().find((a) => a.status === 'done')!;
  const m = new Map<string, Live>();
  for (const a of buildMockAudits()) {
    const pool =
      a.systemId === 'SYS-001'
        ? full.artifacts.map((x) => ({
            ...x,
            id: x.id.replace(full.id, a.id),
            auditId: a.id,
            status: a.status === 'done' ? x.status : 'proposed',
          }))
        : a.artifacts;
    m.set(a.id, { audit: a, pool, runningSince: null, baseIndex: stageIndex(a.stage) });
  }
  return m;
}

function db(): Map<string, Live> {
  store ??= init();
  return store;
}

/** Reset (tests). */
export function resetMockStore(): void {
  store = null;
}

function tick(l: Live, now = Date.now()): AuditDetail {
  const a = l.audit;
  if (a.status === 'running' && l.runningSince != null) {
    let i = l.baseIndex + Math.floor((now - l.runningSince) / STEP_MS);
    // Stop at the first gate after the base index.
    // Work stages with a gate (find_public_data) skip it in mock mode: no candidates score high enough.
    const gate = STAGES.findIndex((s, k) => k > l.baseIndex && s.gate && s.kinds.length === 0);
    if (gate >= 0 && i >= gate) {
      i = gate;
      a.status = 'waiting_approval';
      l.runningSince = null;
    }
    if (i >= STAGES.length) {
      i = STAGES.length - 1;
      a.status = 'done';
      l.runningSince = null;
    }
    if (STAGES[i].id !== a.stage) {
      a.stage = STAGES[i].id;
      a.updatedAt = new Date(now).toISOString();
    }
  }
  const cur = a.status === 'done' ? STAGES.length : stageIndex(a.stage);
  // Reveal artifacts of finished stages (and of the stage under review at a gate).
  a.artifacts = l.pool.filter((x) => {
    const si = STAGES.findIndex((s) => s.kinds.includes(x.kind as never));
    return si >= 0 && si < cur;
  });
  return structuredClone(a);
}

export function mockList(systemId?: string | null): AuditDetail[] {
  return [...db().values()]
    .map((l) => tick(l))
    .filter((a) => !systemId || a.systemId === systemId)
    .sort((x, y) => y.createdAt.localeCompare(x.createdAt));
}

export function mockGet(id: string): AuditDetail | undefined {
  const l = db().get(id);
  return l ? tick(l) : undefined;
}

export function mockDecide(id: string, body: ApprovalIn): ApprovalResult | undefined {
  const l = db().get(id);
  if (!l) return undefined;
  tick(l);
  const now = new Date().toISOString();
  const approval: Approval = {
    id: `${id}-appr-${Date.now().toString(36)}`,
    auditId: id,
    artifactId: body.artifactId ?? null,
    gate: body.gate,
    decision: body.decision,
    reasonCategory: body.reasonCategory ?? null,
    comment: body.comment ?? null,
    edits: body.edits ?? {},
    decidedBy: 'engineer:you',
    at: now,
  };
  l.audit.approvals = [...l.audit.approvals, approval];
  const gateIdx = STAGES.findIndex((s) => s.gate?.id === body.gate);
  const reviewed = new Set<string>(STAGES[gateIdx]?.gate?.reviews ?? []);
  const status = body.decision === 'approved' ? 'approved' : body.decision;
  l.pool = l.pool.map((x) => (reviewed.has(x.kind) ? { ...x, status, updatedAt: now } : x));
  if (body.decision === 'approved' && gateIdx >= 0) {
    l.audit.status = 'running';
    l.audit.stage = STAGES[gateIdx + 1].id;
    l.baseIndex = gateIdx + 1;
    l.runningSince = Date.now();
  } else {
    // Changes requested / rejected: the agent redrafts from the step before the gate.
    l.audit.status = 'running';
    l.baseIndex = Math.max(0, gateIdx - 1);
    l.audit.stage = STAGES[l.baseIndex].id;
    l.runningSince = Date.now();
  }
  l.audit.updatedAt = now;
  return { approval, artifact: null };
}

/** A new mock audit (POST /v1/systems/{id}/audits): runs from load_context to the first gate. */
export function mockStart(systemId: string, data: Record<string, unknown> = {}): AuditDetail {
  const m = db();
  const template = [...m.values()].find((l) => l.audit.systemId === systemId) ?? [...m.values()][0];
  const id = `aud-${systemId.toLowerCase()}-${Date.now().toString(36)}`;
  const now = new Date().toISOString();
  const audit: AuditDetail = {
    id,
    systemId,
    status: 'running',
    stage: STAGES[0].id,
    createdBy: 'engineer:you',
    data: { trigger: 'manual', ...data },
    createdAt: now,
    updatedAt: now,
    artifacts: [],
    approvals: [],
  };
  const pool = (template?.pool ?? []).map((x) => ({
    ...x,
    id: `${id}-${x.kind}-${x.name}`,
    auditId: id,
    status: 'proposed',
  }));
  m.set(id, { audit, pool, runningSince: Date.now(), baseIndex: 0 });
  const { artifacts: _a, approvals: _p, ...out } = tick(m.get(id)!);
  return { ...out, artifacts: [], approvals: [] };
}
