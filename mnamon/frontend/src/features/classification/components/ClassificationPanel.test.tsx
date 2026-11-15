import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryClient } from '@/shared/lib/query-client';
import { TooltipProvider } from '@/shared/ui';
import { ClassificationPanel } from './ClassificationPanel';

const h = vi.hoisted(() => ({
  rows: [] as unknown[],
  start: vi.fn(async () => ({})),
  decide: vi.fn(async () => ({})),
}));

vi.mock('../handlers/classifications', async () => {
  const { toClassifications, toClassification } = await import('../lib/classification');
  return {
    fetchClassifications: vi.fn(async () => toClassifications(h.rows)),
    startClassification: vi.fn(async (...a: unknown[]) => toClassification(await h.start(...(a as [])))),
    decideClassification: vi.fn(async (...a: unknown[]) => toClassification(await h.decide(...(a as [])))),
    fetchObligationsPreview: vi.fn(async () => ({ items: [] })),
  };
});

const RESULT = {
  risk_class: 'minimal_risk',
  route: 'art6_3_exempt',
  annex_basis: null,
  role: 'provider',
  art5_screening: [],
  annex_iii_considered: [{ provision_id: 'AIA.ANNEX_III.4.a', applies: true, why: 'Recruitment.' }],
  art6_3: { considered: true, condition: 'a', profiling: 'no', holds: true, why: 'Only structures CVs.' },
  reasoning: 'A narrow procedural task.',
  counter_arguments: [{ argument: 'If it ranks, 4(a) applies.', would_change_to: 'high_risk' }],
  would_change_if: ['It ranks candidates.'],
  uncertainties: [],
  next_steps: ['Document the Art. 6(4) assessment.'],
  confidence: 0.55,
  citations: [
    { id: 'AIA.6.3', binding: true, status: 'final', quote: 'narrow procedural task' },
    { id: 'INT.guideline.ex12', binding: false, status: 'draft', quote: 'A CV parser…' },
  ],
  key_dates: [],
  iris: { choice: 'high_risk_annex_iii', probabilities: { high_risk_annex_iii: 0.6 } },
  agreement: false,
  needs_human: true,
  needs_human_reasons: ['Iris disagrees: High risk (Annex III).'],
  verifier_problems: [],
};

const row = (status: string, extra: Record<string, unknown> = {}) => ({
  id: 'CLS-SYS-004-20261115-1405',
  system_id: 'SYS-004',
  status,
  kb_version: '2026.11.15-1',
  result: RESULT,
  created_at: '2026-11-15T14:05:00Z',
  events: [],
  ...extra,
});

function setup() {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <TooltipProvider>
        <ClassificationPanel systemId="SYS-004" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  h.rows = [];
  h.start.mockClear();
  h.decide.mockClear();
});

describe('ClassificationPanel', () => {
  it('offers Classify risk when nothing ran yet', async () => {
    setup();
    await userEvent.click(await screen.findByRole('button', { name: /Classify risk/ }));
    expect(h.start).toHaveBeenCalledWith('SYS-004', undefined);
  });

  it('shows a proposal: class, 6(3), citations, counter-arguments and the needs-human banner', async () => {
    h.rows = [row('proposed')];
    setup();
    expect(await screen.findByText('Minimal risk')).toBeInTheDocument();
    expect(screen.getByText('Not high risk: Art. 6(3)(a) derogation')).toBeInTheDocument();
    expect(screen.getByText('Holds')).toBeInTheDocument();
    expect(screen.getByText('Needs a careful human review')).toBeInTheDocument();
    expect(screen.getByText('Iris disagrees: High risk (Annex III).')).toBeInTheDocument();
    expect(screen.getByText('If it ranks, 4(a) applies.')).toBeInTheDocument();
    expect(screen.getByText('Draft')).toBeInTheDocument();
    expect(screen.getByText('Non-binding guidance')).toBeInTheDocument();
  });

  it('shows Iris chips per claim and the grouped checks, strong disagreements first', async () => {
    const claim = (key: string, statement: string, agent: boolean, iris: number | null, strong = false) => ({
      key,
      group: key.split(':')[0],
      provision_id: key.includes('AIA.') ? key.split(':')[1] : null,
      statement,
      agent,
      iris,
      agrees: iris === null ? null : iris >= 0.5 === agent,
      strong_disagreement: strong,
    });
    h.rows = [
      row('proposed', {
        result: {
          ...RESULT,
          iris_claims: [
            claim('annex_iii:AIA.ANNEX_III.4.a', 'It is used in recruitment.', true, 0.93),
            claim('art6_3:condition', 'It performs a narrow procedural task.', true, 0.12, true),
            claim('role', 'The organisation is the provider.', true, null),
          ],
          iris_summary: { checked: 2, agree: 1, disagree: 1 },
        },
      }),
    ];
    setup();
    expect(await screen.findByText('1 of 2 claims agree')).toBeInTheDocument();
    expect(
      screen.getAllByRole('img', {
        name: /Iris agrees with the agent \(93% support\): It is used in recruitment/,
      }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByRole('img', { name: /Iris strongly disagrees with the agent \(12% support\)/ }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByRole('img', { name: /Iris did not run on: The organisation/ }).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText('Independent checks (Oumi Iris)')).toBeInTheDocument();
    expect(screen.getByText('Strong disagreements')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'See the checks' }));
  });

  it('hides the Iris claims on an older run', async () => {
    h.rows = [row('proposed')];
    setup();
    await screen.findByText('Minimal risk');
    expect(screen.queryByText(/claims agree/)).not.toBeInTheDocument();
    expect(screen.queryByText('Independent checks (Oumi Iris)')).not.toBeInTheDocument();
  });

  it('a rejection needs a reason', async () => {
    h.rows = [row('proposed')];
    setup();
    await userEvent.click(await screen.findByRole('button', { name: 'Reject' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Reject' }));
    expect(within(dialog).getByText(/A reason is required/)).toBeInTheDocument();
    expect(h.decide).not.toHaveBeenCalled();
    await userEvent.type(within(dialog).getByLabelText('Why is it wrong?'), 'It also ranks candidates');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Reject' }));
    expect(h.decide).toHaveBeenCalledWith('SYS-004', 'CLS-SYS-004-20261115-1405', {
      decision: 'reject',
      reason: 'It also ranks candidates',
    });
  });

  it('a stale class shows why and re-classifies from it', async () => {
    h.rows = [
      row('stale', {
        events: [
          { action: 'stale', data: { change_id: 'RC-2026.11.15-1', provisions: ['AIA.6.3'] }, at: 'x' },
        ],
      }),
    ];
    setup();
    expect(await screen.findByText(/Stale: a regulation change/)).toBeInTheDocument();
    expect(screen.getByText(/RC-2026.11.15-1 changed AIA.6.3/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Re-classify' }));
    expect(h.start).toHaveBeenCalledWith('SYS-004', 'CLS-SYS-004-20261115-1405');
  });
});
