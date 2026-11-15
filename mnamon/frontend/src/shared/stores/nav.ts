import { create } from 'zustand';

/**
 * Sidebar badge counts, set by features (e.g. NavBadgesSync calls
 * `setBadge('audits', openGates.length)`).
 * Keys are nav item ids from src/app/nav.ts.
 */
interface NavBadgesState {
  badges: Record<string, number>;
  setBadge: (id: string, count: number) => void;
}

export const useNavBadges = create<NavBadgesState>((set) => ({
  badges: {},
  setBadge: (id, count) => set((s) => ({ badges: { ...s.badges, [id]: count } })),
}));
