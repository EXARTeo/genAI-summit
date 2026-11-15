import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryClient } from '@/shared/lib/query-client';
import { TooltipProvider } from '@/shared/ui';
import { RegisterWizard } from './RegisterWizard';

vi.mock('@/shared/lib/env', () => ({ env: { useMocks: true, apiBase: '/api' } }));

const { calls } = vi.hoisted(() => ({ calls: [] as string[] }));
vi.mock('../handlers/onboarding', () => ({
  createSystem: vi.fn(async (b: { id: string }) => {
    calls.push(`create ${b.id}`);
    return { id: b.id };
  }),
  writeTextFile: vi.fn(async (_id: string, path: string) => {
    calls.push(`write ${path}`);
  }),
  uploadFile: vi.fn(async (_id: string, path: string) => {
    calls.push(`upload ${path}`);
  }),
}));

function setup() {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <TooltipProvider>
        <MemoryRouter>
          <RegisterWizard />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  calls.length = 0;
});

describe('RegisterWizard', () => {
  it('proposes the next free id and validates the identity step', async () => {
    setup();
    const id = screen.getByLabelText('System id');
    await waitFor(() => expect(id).toHaveValue('SYS-004'));
    await userEvent.clear(id);
    await userEvent.type(id, 'SYS-001');
    await userEvent.click(screen.getByRole('button', { name: /Next/ }));
    expect(screen.getByText('SYS-001 is already registered.')).toBeInTheDocument();
    expect(screen.getByText('Give the system a name.')).toBeInTheDocument();
    expect(screen.getByText(/Pick how you got the system/)).toBeInTheDocument();
  });

  it('requires the intended purpose', async () => {
    setup();
    await waitFor(() => expect(screen.getByLabelText('System id')).toHaveValue('SYS-004'));
    await userEvent.type(screen.getByLabelText('Name'), 'Thing');
    await userEvent.click(screen.getByLabelText(/Built in-house/));
    await userEvent.click(screen.getByRole('button', { name: /Next/ }));
    expect(screen.getByRole('heading', { name: 'Purpose' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Next/ }));
    expect(screen.getByText('The intended purpose is required.')).toBeInTheDocument();
  });

  it('fills the example and creates the system, card and documents in order', async () => {
    setup();
    await waitFor(() => expect(screen.getByLabelText('System id')).toHaveValue('SYS-004'));
    await userEvent.click(screen.getByRole('button', { name: /Fill example/ }));
    expect(screen.getByLabelText('Name')).toHaveValue('CV Parser');
    for (let i = 0; i < 4; i++) await userEvent.click(screen.getByRole('button', { name: /Next/ }));
    expect(screen.getByRole('heading', { name: 'Review' })).toBeInTheDocument();
    expect(screen.getByText('docs/system-specification.md')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Create system/ }));
    await screen.findByText('CV Parser is registered');
    expect(calls).toEqual([
      'create SYS-004',
      'write system-card.yaml',
      'upload docs/system-specification.md',
    ]);
    expect(screen.getByRole('link', { name: /Plugins tab/ })).toHaveAttribute(
      'href',
      '/systems/SYS-004/plugins',
    );
  });
});
