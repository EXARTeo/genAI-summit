import { create } from 'zustand';

const SIDEBAR_KEY = 'aac.sidebarCollapsed';

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === '1';
  } catch {
    return false;
  }
}

interface UiState {
  sidebarCollapsed: boolean;
  /** Mobile drawer. */
  mobileNavOpen: boolean;
  commandOpen: boolean;
  /** The page fills the content area edge to edge (no padding, no max width, no scroll): a canvas page. */
  fullBleed: boolean;
  setFullBleed: (on: boolean) => void;
  toggleSidebar: () => void;
  setMobileNavOpen: (open: boolean) => void;
  setCommandOpen: (open: boolean) => void;
}

export const useUiStore = create<UiState>((set) => ({
  sidebarCollapsed: readCollapsed(),
  mobileNavOpen: false,
  commandOpen: false,
  fullBleed: false,
  setFullBleed: (fullBleed) => set({ fullBleed }),
  toggleSidebar: () =>
    set((s) => {
      const next = !s.sidebarCollapsed;
      try {
        localStorage.setItem(SIDEBAR_KEY, next ? '1' : '0');
      } catch {
        /* storage blocked */
      }
      return { sidebarCollapsed: next };
    }),
  setMobileNavOpen: (mobileNavOpen) => set({ mobileNavOpen }),
  setCommandOpen: (commandOpen) => set({ commandOpen }),
}));
