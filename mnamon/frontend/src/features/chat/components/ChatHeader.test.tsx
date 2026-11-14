import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { TooltipProvider } from '@/shared/ui';
import type { AgentManifest } from '../lib/types';
import { ChatHeader } from './ChatHeader';

const AGENTS: AgentManifest[] = [
  { slug: 'assistant', name: 'Copilot', description: 'Answers questions.', default: true },
  { slug: 'auditor', name: 'Auditor', description: 'Runs an audit.' },
];

function setup(props: Partial<Parameters<typeof ChatHeader>[0]> = {}) {
  const onAgentChange = vi.fn();
  render(
    <MemoryRouter>
      <TooltipProvider>
        <ChatHeader
          agents={AGENTS}
          agent={AGENTS[0]}
          onAgentChange={onAgentChange}
          onNewChat={vi.fn()}
          {...props}
        />
      </TooltipProvider>
    </MemoryRouter>,
  );
  return { onAgentChange };
}

describe('ChatHeader', () => {
  it('shows the agent as the picker, with a check on the current one', async () => {
    setup();
    await userEvent.click(screen.getByRole('button', { name: 'Agent: Copilot' }));
    expect(screen.getByLabelText('Search agents')).toHaveFocus();
    expect(screen.getAllByRole('option')).toHaveLength(2);
  });

  it('filters by the search and picks with Enter', async () => {
    const { onAgentChange } = setup();
    await userEvent.click(screen.getByRole('button', { name: 'Agent: Copilot' }));
    await userEvent.keyboard('audit');
    expect(screen.getAllByRole('option')).toHaveLength(1);
    await userEvent.keyboard('{Enter}');
    expect(onAgentChange).toHaveBeenCalledWith(AGENTS[1]);
    expect(screen.queryByRole('option')).toBeNull();
  });

  it('closes on Escape without picking', async () => {
    const { onAgentChange } = setup();
    await userEvent.click(screen.getByRole('button', { name: 'Agent: Copilot' }));
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('option')).toBeNull();
    expect(onAgentChange).not.toHaveBeenCalled();
  });

  it('links the subject and offers the conversation actions', async () => {
    const onPin = vi.fn();
    setup({
      title: 'Why is F-001 a gap?',
      subject: { label: 'CV Screener', systemId: 'SYS-001' },
      conversation: { pinned: false, onPin, onArchive: vi.fn(), onDelete: vi.fn() },
    });
    expect(screen.getByRole('link', { name: /CV Screener/ })).toHaveAttribute('href', '/systems/SYS-001');
    await userEvent.click(screen.getByRole('button', { name: 'Conversation actions' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Pin' }));
    expect(onPin).toHaveBeenCalled();
  });

  it('has no conversation actions in a new chat', () => {
    setup();
    expect(screen.queryByRole('button', { name: 'Conversation actions' })).toBeNull();
  });
});
