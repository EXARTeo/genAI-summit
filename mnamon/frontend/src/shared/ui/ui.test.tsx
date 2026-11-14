import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import {
  Button,
  CodeBlock,
  DataTable,
  EmptyState,
  FileTree,
  StatusPill,
  Stepper,
  TooltipProvider,
} from './index';

describe('shared/ui', () => {
  it('Button shows a spinner and disables itself while loading', () => {
    render(<Button loading>Save</Button>);
    const btn = screen.getByRole('button', { name: 'Save' });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute('aria-busy', 'true');
  });

  it('StatusPill humanises the status and picks a tone', () => {
    render(<StatusPill status="needs_approval" />);
    expect(screen.getByText('needs approval')).toBeInTheDocument();
  });

  it('Stepper renders every state', () => {
    render(
      <Stepper
        steps={[
          { id: 'a', title: 'Load context', state: 'done' },
          { id: 'b', title: 'Plan tests', state: 'needs-approval' },
          { id: 'c', title: 'Generate data', state: 'active' },
          { id: 'd', title: 'Execute', state: 'pending' },
          { id: 'e', title: 'Report', state: 'blocked' },
        ]}
      />,
    );
    expect(screen.getByText('Needs approval')).toBeInTheDocument();
    expect(screen.getByText('Blocked')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument(); // pending shows its number
  });

  it('DataTable sorts when a header is clicked', async () => {
    const rows = [
      { id: 'b', score: 2 },
      { id: 'a', score: 10 },
      { id: 'c', score: 1 },
    ];
    render(
      <DataTable
        rows={rows}
        rowKey={(r) => r.id}
        columns={[
          { id: 'id', header: 'Id' },
          { id: 'score', header: 'Score', sortValue: (r) => r.score },
        ]}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /score/i }));
    const cells = screen
      .getAllByRole('row')
      .slice(1)
      .map((r) => r.textContent);
    expect(cells).toEqual(['c1', 'b2', 'a10']);
  });

  it('FileTree builds folders from flat paths and selects files', async () => {
    const onSelect = vi.fn();
    render(
      <FileTree
        entries={[{ path: 'system-card.yaml' }, { path: 'plugins/ranker/plugin.yaml' }]}
        onSelect={onSelect}
      />,
    );
    expect(screen.getByText('plugins')).toBeInTheDocument();
    await userEvent.click(screen.getByText('system-card.yaml'));
    expect(onSelect).toHaveBeenCalledWith('system-card.yaml');
  });

  it('CodeBlock highlights YAML keys', () => {
    const { container } = render(<CodeBlock code={'risk_class: high_risk\n'} language="yaml" />);
    expect(container.querySelector('.text-primary')?.textContent).toBe('risk_class');
  });

  it('EmptyState renders title, description and action', () => {
    render(
      <TooltipProvider>
        <EmptyState title="Nothing" description="Add one" action={<Button>Add</Button>} />
      </TooltipProvider>,
    );
    expect(screen.getByText('Nothing')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add' })).toBeInTheDocument();
  });
});
