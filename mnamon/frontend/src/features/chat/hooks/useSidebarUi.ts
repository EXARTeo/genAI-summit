/**
 * Sidebar UI state for the conversation list: which sections are folded (remembered per browser,
 * like magenticx's `loadSidebarSectionOpen`) and whether the chat search panel is open.
 *
 * The search panel is opened from the sidebar's "Search chats" row, the `/search` command and
 * Ctrl/⌘+Shift+S: call `useChatSearchPanel.getState().setOpen(true)` from anywhere.
 */
import { useCallback, useState } from 'react';
import { create } from 'zustand';

interface ChatSearchPanelState {
  open: boolean;
  setOpen: (open: boolean) => void;
}

export const useChatSearchPanel = create<ChatSearchPanelState>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}));

export type SidebarSectionKey = 'pinned' | 'chats';

const storageKey = (key: SidebarSectionKey) => `mnamon.chat.sidebar.${key}.open`;

function readOpen(key: SidebarSectionKey): boolean {
  try {
    return localStorage.getItem(storageKey(key)) !== 'false';
  } catch {
    return true;
  }
}

/** A folding section's open state, persisted (open by default; storage failures are ignored). */
export function useSectionOpen(key: SidebarSectionKey): [boolean, () => void] {
  const [open, setOpen] = useState(() => readOpen(key));
  const toggle = useCallback(() => {
    setOpen((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(storageKey(key), String(next));
      } catch {
        // Private mode or blocked storage: the fold still works for this visit.
      }
      return next;
    });
  }, [key]);
  return [open, toggle];
}
