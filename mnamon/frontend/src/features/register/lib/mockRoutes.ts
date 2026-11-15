// Mock routes for the findings register, registered by src/shared/lib/mocks/handlers/findings-register.ts.
// A small in-memory register per system: two open gaps, one needing review, one accepted risk, one resolved.
import { mockError, type MockRoute } from '@/shared/lib/mocks';
import type { Register, RegisterEvent, RegisterItem, RegisterSummary } from './types';

const A1 = 'MOCK-20261114-0900';
const A2 = 'MOCK-20261115-0900';

function ev(
  at: string,
  audit: string | null,
  kind: string,
  from: string | null,
  to: string,
  verdict: string,
  note: string | null = null,
): RegisterEvent {
  return {
    at,
    audit_id: audit,
    actor: audit ? `audit:${audit}` : 'client:mock',
    kind,
    from,
    to,
    verdict,
    note,
  };
}

function item(systemId: string, obligation: string, extra: Partial<RegisterItem>): RegisterItem {
  return {
    id: `${systemId}:${obligation}`,
    system_id: systemId,
    obligation_id: obligation,
    state: 'open',
    verdict: 'gap',
    severity: 'high',
    article: null,
    title: null,
    gap_id: null,
    first_seen_audit_id: A1,
    last_seen_audit_id: A2,
    last_finding_id: null,
    opened_at: '2026-11-14T09:30:00Z',
    closed_by: null,
    close_reason: null,
    closed_at: null,
    created_at: '2026-11-14T09:30:00Z',
    updated_at: '2026-11-15T09:30:00Z',
    last_status: 'still_open',
    last_reasoning: null,
    last_evidence: [],
    history: [],
    ...extra,
  };
}

function seed(systemId: string): RegisterItem[] {
  const t1 = '2026-11-14T09:30:00Z';
  const t2 = '2026-11-15T09:30:00Z';
  return [
    item(systemId, 'OBL.AIA.10.2.f.bias-examination', {
      article: 'Art. 10(2)(f)',
      title: 'Examine the data for biases that affect health, safety or fundamental rights',
      severity: 'critical',
      gap_id: `G-${systemId}-01`,
      last_reasoning: 'Selection-rate ratio 0.62 for postcode group B, below the org threshold 0.8.',
      history: [ev(t1, A1, 'opened', null, 'open', 'gap'), ev(t2, A2, 'still_open', 'open', 'open', 'gap')],
    }),
    item(systemId, 'OBL.AIA.15.1.accuracy', {
      article: 'Art. 15(1)',
      title: 'Appropriate level of accuracy',
      verdict: 'partial',
      severity: 'medium',
      last_status: 'new',
      first_seen_audit_id: A2,
      history: [ev(t2, A2, 'opened', null, 'open', 'partial')],
    }),
    item(systemId, 'OBL.AIA.9.2.risk-identification', {
      article: 'Art. 9(2)',
      title: 'Identify and analyse known and foreseeable risks',
      verdict: 'inconclusive',
      severity: null,
      history: [
        ev(t1, A1, 'opened', null, 'open', 'inconclusive'),
        ev(t2, A2, 'still_open', 'open', 'open', 'inconclusive'),
      ],
    }),
    item(systemId, 'OBL.AIA.13.instructions-for-use', {
      article: 'Art. 13',
      title: 'Instructions for use',
      state: 'closed',
      verdict: 'not_assessable_by_testing',
      severity: 'low',
      closed_by: 'client:mock',
      close_reason: 'Instructions are maintained in the product wiki; reviewed by the AI Officer.',
      closed_at: '2026-11-14T12:00:00Z',
      last_status: 'accepted_risk',
      history: [
        ev(t1, A1, 'opened', null, 'open', 'not_assessable_by_testing'),
        ev(
          '2026-11-14T12:00:00Z',
          null,
          'closed',
          'open',
          'closed',
          'not_assessable_by_testing',
          'Instructions are maintained in the product wiki; reviewed by the AI Officer.',
        ),
        ev(t2, A2, 'still_open', 'closed', 'closed', 'not_assessable_by_testing'),
      ],
    }),
    item(systemId, 'OBL.AIA.15.4.robustness', {
      article: 'Art. 15(4)',
      title: 'Resilience to errors, faults and inconsistencies',
      state: 'resolved',
      verdict: 'pass',
      severity: null,
      closed_by: `audit:${A2}`,
      closed_at: t2,
      close_reason: `Audit ${A2} found it passing.`,
      last_status: 'resolved',
      history: [
        ev(t1, A1, 'opened', null, 'open', 'gap'),
        ev(t2, A2, 'resolved', 'open', 'resolved', 'pass'),
      ],
    }),
  ];
}

const store = new Map<string, RegisterItem[]>();
const itemsOf = (systemId: string) => {
  if (!store.has(systemId)) store.set(systemId, seed(systemId));
  return store.get(systemId)!;
};

function summary(items: RegisterItem[]): RegisterSummary {
  const by = (k: (i: RegisterItem) => string) =>
    items.reduce<Record<string, number>>((m, i) => ({ ...m, [k(i)]: (m[k(i)] ?? 0) + 1 }), {});
  const open = items.filter((i) => i.state === 'open');
  return {
    total: items.length,
    by_state: by((i) => i.state),
    by_verdict: by((i) => i.verdict),
    open_gaps: open.filter((i) => i.verdict !== 'inconclusive').length,
    needs_review: open.filter((i) => i.verdict === 'inconclusive').length,
    accepted_risks: items.filter((i) => i.state === 'closed').length,
    resolved: items.filter((i) => i.state === 'resolved').length,
    monitoring: items.filter((i) => i.state === 'monitoring').length,
  };
}

const notFound = () => Promise.reject(mockError(404, 'Register item not found.'));

export const registerRoutes: MockRoute[] = [
  {
    method: 'GET',
    path: '/v1/systems/:systemId/register',
    handler: ({ params }): Register => {
      const items = itemsOf(params.systemId);
      return { system_id: params.systemId, summary: summary(items), items };
    },
  },
  {
    method: 'GET',
    path: '/v1/systems/:systemId/register/:obligationId',
    handler: ({ params }) =>
      itemsOf(params.systemId).find((i) => i.obligation_id === params.obligationId) ?? notFound(),
  },
  {
    method: 'POST',
    path: '/v1/systems/:systemId/register/:obligationId/close',
    handler: ({ params, body }) => {
      const row = itemsOf(params.systemId).find((i) => i.obligation_id === params.obligationId);
      if (!row) return notFound();
      const reason = String((body as { reason?: string } | undefined)?.reason ?? '').trim();
      if (!reason) return Promise.reject(mockError(422, 'A reason is required to close an item.'));
      if (row.state === 'closed') return Promise.reject(mockError(409, 'The item is already closed.'));
      const at = new Date().toISOString();
      row.history = [...row.history, ev(at, null, 'closed', row.state, 'closed', row.verdict, reason)];
      Object.assign(row, { state: 'closed', closed_by: 'client:mock', close_reason: reason, closed_at: at });
      return row;
    },
  },
  {
    method: 'POST',
    path: '/v1/systems/:systemId/register/:obligationId/reopen',
    handler: ({ params, body }) => {
      const row = itemsOf(params.systemId).find((i) => i.obligation_id === params.obligationId);
      if (!row) return notFound();
      if (row.state === 'open') return Promise.reject(mockError(409, 'The item is already open.'));
      const at = new Date().toISOString();
      const note = String((body as { reason?: string } | undefined)?.reason ?? '').trim() || null;
      row.history = [...row.history, ev(at, null, 'reopened', row.state, 'open', row.verdict, note)];
      Object.assign(row, {
        state: 'open',
        closed_by: null,
        close_reason: null,
        closed_at: null,
        opened_at: at,
      });
      return row;
    },
  },
];
