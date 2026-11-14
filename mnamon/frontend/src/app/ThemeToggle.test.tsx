import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { THEME_STORAGE_KEY, useThemeStore } from '@/shared/stores/theme';
import { TooltipProvider } from '@/shared/ui';
import { ThemeToggle } from './ThemeToggle';

describe('ThemeToggle', () => {
  beforeEach(() => {
    useThemeStore.setState({ preference: 'system', resolved: 'light' });
    document.documentElement.removeAttribute('data-theme');
  });

  it('switches to dark, persists the choice and sets data-theme', async () => {
    const user = userEvent.setup();
    render(
      <TooltipProvider>
        <ThemeToggle />
      </TooltipProvider>,
    );
    await user.click(screen.getByTestId('theme-toggle'));
    await user.click(await screen.findByRole('menuitem', { name: /dark/i }));
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
    expect(useThemeStore.getState().resolved).toBe('dark');
  });

  it('system resolves from prefers-color-scheme (light in jsdom)', () => {
    useThemeStore.getState().setPreference('system');
    expect(useThemeStore.getState().resolved).toBe('light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });
});
