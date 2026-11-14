import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { TooltipProvider } from '@/shared/ui';
import { TopBar } from './TopBar';
import { TopbarExtra } from './topbarSlot';

const renderAt = (path: string, extra?: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <TooltipProvider>
        <TopBar />
        {extra && <TopbarExtra>{extra}</TopbarExtra>}
      </TooltipProvider>
    </MemoryRouter>,
  );

describe('TopBar slot', () => {
  it('shows the section label when no page fills it', () => {
    renderAt('/audits');
    expect(screen.getByText('Audits')).toBeInTheDocument();
  });

  it('shows the page content instead of the label, keeping the theme toggle', () => {
    renderAt('/chat', 'Copilot header');
    expect(screen.getByText('Copilot header').closest('[data-topbar-slot]')).not.toBeNull();
    expect(screen.queryByText('Chat')).toBeNull();
    expect(screen.getByRole('button', { name: /theme/i })).toBeInTheDocument();
  });
});
