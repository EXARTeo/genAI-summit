// Smoke test: every route renders in mock mode inside the real shell, with no
// error boundary and no console.error.
import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { TooltipProvider } from '@/shared/ui';

vi.mock('@/shared/lib/env', () => ({ env: { useMocks: true, apiBase: '/api' } }));

const ROUTES: [string, RegExp][] = [
  ['/', /Needs your decision/],
  ['/systems', /AI systems/],
  ['/systems/SYS-001', /CV Screener/],
  ['/systems/SYS-001/folder', /\/systems\/SYS-001/],
  ['/systems/SYS-001/plugins', /Pipeline placement/],
  ['/systems/SYS-001/rules', /Add rule/],
  ['/systems/SYS-001/lessons', /Page not found|CV Screener/],
  ['/audits', /Audits/],
  ['/audits/aud-sys001-r2?step=profile_model', /Feature sensitivity/],
  ['/approvals', /Approvals/],
  ['/regulation', /Regulation/],
  ['/chat', /Chat/],
  ['/settings', /Page not found/],
  ['/memory', /Page not found/],
  ['/nope', /Page not found/],
];

beforeAll(() => {
  // React Flow / layout measurements are not available in jsdom.
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, value: 300 });
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 600 });
});

afterEach(() => vi.restoreAllMocks());

describe('routes (mock mode)', () => {
  it.each(ROUTES)('%s renders', async (path, expected) => {
    const errors: unknown[] = [];
    vi.spyOn(console, 'error').mockImplementation((...a) => errors.push(a));
    const { default: App } = await import('./App');
    const { createQueryClient } = await import('@/shared/lib/query-client');
    render(
      <QueryClientProvider client={createQueryClient()}>
        <TooltipProvider>
          <MemoryRouter
            initialEntries={[path]}
            future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
          >
            <App />
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getAllByText(expected).length).toBeGreaterThan(0), { timeout: 8000 });
    expect(screen.queryByText(/This page crashed/)).toBeNull();
    expect(errors).toEqual([]);
  });
});
