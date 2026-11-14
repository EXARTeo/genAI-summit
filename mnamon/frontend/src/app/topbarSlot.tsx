import { useEffect, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { create } from 'zustand';

/**
 * The top bar's content slot, for a page that brings its own header row (the chat: agent
 * picker, subject, conversation actions), so the card shows one header instead of two.
 *
 * The TopBar renders a <TopbarSlotTarget />; a page renders <TopbarExtra>…</TopbarExtra>
 * anywhere in its tree and the content is portalled into it. While something is portalled
 * the TopBar hides its section label; the menu, search and theme buttons stay.
 * Modelled on `sidebarSlot.tsx`.
 */
interface TopbarSlotState {
  target: HTMLElement | null;
  /** How many TopbarExtra are mounted (normally 0 or 1). */
  filled: number;
  setTarget: (el: HTMLElement | null) => void;
  fill: (delta: 1 | -1) => void;
}

const useTopbarSlotStore = create<TopbarSlotState>((set) => ({
  target: null,
  filled: 0,
  setTarget: (target) => set({ target }),
  fill: (delta) => set((s) => ({ filled: Math.max(0, s.filled + delta) })),
}));

/** True while a page puts its own content in the top bar. */
export const useTopbarFilled = () => useTopbarSlotStore((s) => s.filled > 0);

/** Where the top bar lets a page put its header content. */
export function TopbarSlotTarget({ className }: { className?: string }) {
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  const setTarget = useTopbarSlotStore((s) => s.setTarget);
  useEffect(() => {
    if (!el) return;
    setTarget(el);
    return () => setTarget(null);
  }, [el, setTarget]);
  return <div ref={setEl} data-topbar-slot className={className} />;
}

/** Render children into the top bar (replacing its section label). */
export function TopbarExtra({ children }: { children: ReactNode }) {
  const target = useTopbarSlotStore((s) => s.target);
  const fill = useTopbarSlotStore((s) => s.fill);
  useEffect(() => {
    fill(1);
    return () => fill(-1);
  }, [fill]);
  return target ? createPortal(children, target) : null;
}
