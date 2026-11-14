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
  /** Memory entry shown in the global side sheet (opened from "applied MEM-…" chips). */
  memoryEntryId: string | null;
  toggleSidebar: () => void;
  setMobileNavOpen: (open: boolean) => void;
  setCommandOpen: (open: boolean) => void;
  openMemory: (id: string | null) => void;
}

export const useUiStore = create<UiState>((set) => ({
  sidebarCollapsed: readCollapsed(),
  mobileNavOpen: false,
  commandOpen: false,
  memoryEntryId: null,
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
  openMemory: (memoryEntryId) => set({ memoryEntryId }),
}));
