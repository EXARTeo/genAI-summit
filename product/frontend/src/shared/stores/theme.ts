import { create } from 'zustand';

/** Same key as public/theme-init.js (runs before React to avoid a flash). */
export const THEME_STORAGE_KEY = 'aac.theme';

export type ThemePreference = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-color-scheme: dark)').matches;
}

export function resolveTheme(pref: ThemePreference): ResolvedTheme {
  return pref === 'system' ? (systemPrefersDark() ? 'dark' : 'light') : pref;
}

function readPreference(): ThemePreference {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY);
    if (v === 'light' || v === 'dark' || v === 'system') return v;
  } catch {
    /* storage blocked */
  }
  return 'system';
}

export function applyTheme(resolved: ResolvedTheme, animate = false): void {
  const root = document.documentElement;
  if (animate) {
    root.classList.add('theme-transition');
    window.setTimeout(() => root.classList.remove('theme-transition'), 250);
  }
  root.setAttribute('data-theme', resolved);
}

interface ThemeState {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (p: ThemePreference) => void;
  /** Re-resolve after the OS theme changed (only matters for `system`). */
  syncSystem: () => void;
}

const initial = readPreference();

export const useThemeStore = create<ThemeState>((set, get) => ({
  preference: initial,
  resolved: resolveTheme(initial),
  setPreference: (preference) => {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, preference);
    } catch {
      /* storage blocked */
    }
    const resolved = resolveTheme(preference);
    applyTheme(resolved, true);
    set({ preference, resolved });
  },
  syncSystem: () => {
    if (get().preference !== 'system') return;
    const resolved = resolveTheme('system');
    applyTheme(resolved, true);
    set({ resolved });
  },
}));
