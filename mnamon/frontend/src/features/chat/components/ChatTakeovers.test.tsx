import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { TooltipProvider } from '@/shared/ui';
import type { AskUserQuestion } from '../lib/hitl';
import type { Approval } from '../lib/timeline';
import { AskUserTakeover } from './AskUserTakeover';
import { HitlTakeover } from './HitlTakeover';

const QUESTIONS: AskUserQuestion[] = [
  { id: 'q1', question: 'Which system?', options: ['CV Screener', 'Credit Scorer', 'Both'], multiple: false },
  { id: 'q2', question: 'Which checks?', options: ['Bias', 'Robustness', 'Logging'], multiple: true },
];

const ask = (questions = QUESTIONS): Approval => ({
  kind: 'hitl',
  id: 'int-ask',
  threadId: 't1',
  status: 'pending',
  content: { value: { type: 'ask_user', questions } },
  questions,
});

const gate = (requests: unknown[]): Approval => ({
  kind: 'hitl',
  id: 'int-gate',
  threadId: 't1',
  status: 'pending',
  content: { value: { action_requests: requests } },
});

const renderAsk = (onAnswer = vi.fn().mockResolvedValue(undefined), questions = QUESTIONS) => {
  render(<AskUserTakeover approval={ask(questions)} agentName="Copilot" onAnswer={onAnswer} />);
  return onAnswer;
};

describe('AskUserTakeover', () => {
  it('asks one question at a time, numbered, with the agent and step', () => {
    renderAsk();
    expect(screen.getByText('A few quick questions')).toBeInTheDocument();
    expect(screen.getByText('Copilot · question 1 of 2')).toBeInTheDocument();
    const group = screen.getByRole('radiogroup', { name: 'Which system?' });
    expect(
      within(group)
        .getAllByRole('radio')
        .map((r) => r.textContent),
    ).toEqual(['1CV Screener', '2Credit Scorer', '3Both']);
    expect(screen.queryByText('Which checks?')).toBeNull();
  });

  it('picks with the number keys, then moves on by itself', async () => {
    renderAsk();
    await userEvent.keyboard('2');
    expect(screen.getByRole('radio', { name: /Credit Scorer/ })).toHaveAttribute('aria-checked', 'true');
    await waitFor(() => expect(screen.getByText('Which checks?')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Question 1, answered' })).toBeInTheDocument();
  });

  it('sends every answer in the order offered; skip sends null', async () => {
    const onAnswer = renderAsk();
    await userEvent.click(screen.getByRole('radio', { name: /Both/ }));
    await waitFor(() => screen.getByText('Which checks?'));
    await userEvent.click(screen.getByRole('checkbox', { name: /Logging/ }));
    await userEvent.click(screen.getByRole('checkbox', { name: /Bias/ }));
    fireEvent.change(screen.getByRole('textbox', { name: /own answer to: Which checks/ }), {
      target: { value: '  and transparency  ' },
    });
    expect(screen.getByRole('group', { name: 'Your answers' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /send answers/i }));
    await waitFor(() => expect(onAnswer).toHaveBeenCalledTimes(1));
    expect(onAnswer.mock.calls[0][0]).toEqual([
      { id: 'q1', selected: ['Both'], text: '' },
      { id: 'q2', selected: ['Bias', 'Logging'], text: 'and transparency' },
    ]);
  });

  it('skips with null', async () => {
    const onAnswer = renderAsk();
    await userEvent.click(screen.getByRole('button', { name: /skip/i }));
    await waitFor(() => expect(onAnswer).toHaveBeenCalledWith(null));
  });

  it('keeps the answers when sending fails', async () => {
    renderAsk(vi.fn().mockRejectedValue(new Error('409')), [QUESTIONS[0]]);
    expect(screen.getByText('Copilot has a question')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: /CV Screener/ }));
    await userEvent.click(screen.getByRole('button', { name: /send answer/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('radio', { name: /CV Screener/ })).toHaveAttribute('aria-checked', 'true');
  });
});

describe('HitlTakeover', () => {
  const renderGate = (requests: unknown[], onResolve = vi.fn().mockResolvedValue(undefined)) => {
    render(
      <TooltipProvider>
        <HitlTakeover approval={gate(requests)} pendingCount={1} onResolve={onResolve} />
      </TooltipProvider>,
    );
    return onResolve;
  };

  it('is compact: what the tool does, details behind the chevron', async () => {
    renderGate([
      {
        name: 'write_finding_note',
        args: { path: 'findings/F-001.md' },
        description: 'Write a finding note',
      },
    ]);
    expect(screen.getByText('Approval required')).toBeInTheDocument();
    expect(screen.getByText('Write a finding note')).toBeInTheDocument();
    expect(screen.queryByText('findings/F-001.md')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Show approval details' }));
    expect(screen.getByText('findings/F-001.md')).toBeInTheDocument();
  });

  it('rejects with the typed reason', async () => {
    const onResolve = renderGate([{ name: 'write_finding_note', args: {} }]);
    await userEvent.type(screen.getByRole('textbox', { name: 'Reason (optional)' }), 'wrong folder');
    await userEvent.click(screen.getByRole('button', { name: /Reject/ }));
    expect(onResolve).toHaveBeenCalledWith([{ decision: 'reject', reason: 'wrong folder' }]);
  });

  it('approves on Enter in the reason field', async () => {
    const onResolve = renderGate([{ name: 'write_finding_note', args: {} }]);
    await userEvent.type(screen.getByRole('textbox', { name: 'Reason (optional)' }), '{Enter}');
    expect(onResolve).toHaveBeenCalledWith([{ decision: 'approve' }]);
  });

  it('steps through a batch, then sends every decision together', async () => {
    const onResolve = renderGate([
      { name: 'write_file', args: { path: 'a.md' } },
      { name: 'delete_file', args: { path: 'b.md' } },
    ]);
    expect(screen.getByText('Approve 2 actions')).toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(2);
    expect(screen.queryByRole('button', { name: /Send decisions/ })).toBeNull();
    await userEvent.type(screen.getByLabelText('Rejection reason for action 1'), 'not yet');
    await userEvent.click(screen.getByRole('button', { name: /Reject/ }));
    await userEvent.click(screen.getByRole('button', { name: /^Approve$/ }));
    expect(screen.getByRole('tab', { name: /Action 1: .*\(rejected\)/ })).toBeInTheDocument();
    expect(screen.getByText(/1 approved · 1 rejected/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Send decisions/ }));
    expect(onResolve).toHaveBeenCalledWith([
      { decision: 'reject', reason: 'not yet' },
      { decision: 'approve' },
    ]);
  });
});
