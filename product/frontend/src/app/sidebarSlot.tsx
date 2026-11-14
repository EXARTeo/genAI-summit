import { useEffect, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { create } from 'zustand';

/**
 * The sidebar's extra region (below the nav), for a feature that needs its own
 * list there, e.g. the chat's conversation list on /chat routes.
 *
 * The shell renders a <SidebarSlotTarget /> in the desktop rail and in the mobile
 * drawer; a feature renders <SidebarExtra>…</SidebarExtra> anywhere in its page
 * tree and the content is portalled into the visible target (the drawer while it
 * is open, otherwise the rail). It is hidden while the rail is collapsed.
 */
interface SlotState {
  targets: HTMLElement[];
  register: (el: HTMLElement) => void;
  unregister: (el: HTMLElement) => void;
}

const useSlotStore = create<SlotState>((set) => ({
  targets: [],
  register: (el) => set((s) => ({ targets: [...s.targets.filter((t) => t !== el), el] })),
  unregister: (el) => set((s) => ({ targets: s.targets.filter((t) => t !== el) })),
}));

/** Where the shell lets features put sidebar content. The last mounted target wins. */
export function SidebarSlotTarget({ className }: { className?: string }) {
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  const register = useSlotStore((s) => s.register);
  const unregister = useSlotStore((s) => s.unregister);
  useEffect(() => {
    if (!el) return;
    register(el);
    return () => unregister(el);
  }, [el, register, unregister]);
  return <div ref={setEl} data-sidebar-slot className={className} />;
}

/** Render children into the sidebar's extra region (no-op while no target is mounted). */
export function SidebarExtra({ children }: { children: ReactNode }) {
  const target = useSlotStore((s) => s.targets[s.targets.length - 1]);
  return target ? createPortal(children, target) : null;
}
