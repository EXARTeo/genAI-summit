import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { TooltipProvider } from '@/shared/ui';
import { AiActionBar, UserActionBar } from './ActionBars';
import { BranchControls } from './BranchControls';
import { MarkdownTable } from './MarkdownTable';
import { MessageUsage } from './MessageUsage';

const wrap = (ui: React.ReactElement) => render(<TooltipProvider>{ui}</TooltipProvider>);
const noBranch = { index: 0, count: 1, onSelect: () => undefined };

describe('BranchControls', () => {
  it('renders nothing for a single version', () => {
    const { container } = wrap(<BranchControls index={0} count={1} onSelect={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows ‹ 2/3 › and moves between versions, clamped at the ends', () => {
    const onSelect = vi.fn();
    const { rerender } = wrap(<BranchControls index={1} count={3} onSelect={onSelect} />);
    expect(screen.getByText('2/3')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Previous version' }));
    fireEvent.click(screen.getByRole('button', { name: 'Next version' }));
    expect(onSelect.mock.calls).toEqual([[0], [2]]);
    rerender(
      <TooltipProvider>
        <BranchControls index={2} count={3} onSelect={onSelect} />
      </TooltipProvider>,
    );
    expect(screen.getByRole('button', { name: 'Next version' })).toBeDisabled();
  });
});

describe('AiActionBar', () => {
  const setup = (liked: boolean | null = null) => {
    const onRate = vi.fn();
    const onRetry = vi.fn();
    const onOpenSubagents = vi.fn();
    wrap(
      <AiActionBar
        text="answer"
        time="10:05"
        agentName="Copilot"
        liked={liked}
        onRate={onRate}
        onRetry={onRetry}
        subagentCount={2}
        onOpenSubagents={onOpenSubagents}
        branch={{ index: 0, count: 2, onSelect: vi.fn() }}
      />,
    );
    return { onRate, onRetry, onOpenSubagents };
  };

  it('shows time, agent, copy, thumbs, sub-agent badge and the branch switcher', () => {
    const { onRate, onOpenSubagents } = setup();
    expect(screen.getByText('10:05')).toBeInTheDocument();
    expect(screen.getByText('Copilot')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();
    expect(screen.getByText('1/2')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Like' }));
    fireEvent.click(screen.getByRole('button', { name: 'Dislike' }));
    expect(onRate.mock.calls).toEqual([[true], [false]]);
    fireEvent.click(screen.getByRole('button', { name: 'Sub-agents (2)' }));
    expect(onOpenSubagents).toHaveBeenCalled();
  });

  it('shows only the thumb an answer got', () => {
    setup(true);
    expect(screen.getByRole('button', { name: 'Remove like' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByRole('button', { name: 'Dislike' })).not.toBeInTheDocument();
  });

  it('offers Try again in the ⋯ menu', async () => {
    const { onRetry } = setup();
    await userEvent.click(screen.getByRole('button', { name: 'More message actions' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalled();
  });
});

describe('UserActionBar', () => {
  it('copies and edits', () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const onEdit = vi.fn();
    wrap(<UserActionBar text="hello" onEdit={onEdit} branch={noBranch} />);
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
    expect(writeText).toHaveBeenCalledWith('hello');
    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Edit message' }));
    expect(onEdit).toHaveBeenCalled();
  });
});

describe('MessageUsage', () => {
  it('shows the compact total, nothing without usage', () => {
    const { rerender } = wrap(
      <MessageUsage
        usage={{ inputTokens: 4200, outputTokens: 612, modelCalls: 2, model: 'gemini' }}
        tools={2}
        seconds={9}
      />,
    );
    expect(screen.getByLabelText('Token usage: 4,812 tokens')).toHaveTextContent('4.8k');
    rerender(
      <TooltipProvider>
        <MessageUsage usage={null} tools={0} seconds={null} />
      </TooltipProvider>,
    );
    expect(screen.queryByLabelText(/Token usage/)).not.toBeInTheDocument();
  });
});

describe('MarkdownTable', () => {
  it('copies the rendered rows as TSV when ClipboardItem is missing', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    wrap(
      <MarkdownTable>
        <thead>
          <tr>
            <th>Group</th>
            <th>Rate</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>female</td>
            <td>0.71</td>
          </tr>
        </tbody>
      </MarkdownTable>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Copy table' }));
    await screen.findByRole('button', { name: 'Table copied' });
    expect(writeText).toHaveBeenCalledWith('Group\tRate\nfemale\t0.71');
  });
});
