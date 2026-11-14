/*
 * Written here rather than taken from a library: a port of magenticx's `SectionToggle` +
 * `SidebarSection` (ChatSidebar.tsx). A plain disclosure button, not Radix Collapsible, whose
 * Content hides itself the instant `open` flips and would cut the list's exit fade.
 */
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { ChevronRight } from 'lucide-react';
import type { ReactNode, Ref, UIEventHandler } from 'react';
import { cn } from '@/shared/lib/utils';
import { sectionListMotion } from '../../lib/sidebarMotion';

/** A small heading that folds its list ("Pinned", "Chats"). */
function SectionToggle({
  label,
  open,
  controlsId,
  onToggle,
}: {
  label: string;
  open: boolean;
  controlsId: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-controls={controlsId}
      onClick={onToggle}
      className="group/section flex h-10 shrink-0 items-center gap-1 self-start rounded-lg px-2.5 text-left text-[13px] font-medium text-muted outline-none transition-colors duration-150 hover:text-text focus-visible:text-text focus-visible:ring-2 focus-visible:ring-ring md:h-8"
    >
      <span>{label}</span>
      <ChevronRight
        aria-hidden="true"
        className={cn(
          'size-3.5 opacity-60 transition-[transform,opacity] duration-200 ease-out group-hover/section:opacity-100 group-focus-visible/section:opacity-100 motion-reduce:transition-none',
          open && 'rotate-90',
        )}
      />
    </button>
  );
}

/** One folding section: its heading and the list it folds (the list fades and drops in). */
export function SidebarSection({
  label,
  open,
  onToggle,
  listId,
  className,
  listClassName,
  listRef,
  onScroll,
  actions,
  children,
}: {
  label: string;
  /** Small icon buttons on the right of the heading (e.g. New chat, Search). */
  actions?: ReactNode;
  open: boolean;
  onToggle: () => void;
  listId: string;
  className?: string;
  /** The list's own box: its cap (a long list scrolls on its own) and padding. */
  listClassName?: string;
  listRef?: Ref<HTMLDivElement>;
  onScroll?: UIEventHandler<HTMLDivElement>;
  children: ReactNode;
}) {
  const reduceMotion = useReducedMotion();
  return (
    <section className={cn('flex flex-col', className)} aria-label={label}>
      <div className="flex items-center justify-between gap-1 pr-1">
        <SectionToggle label={label} open={open} controlsId={listId} onToggle={onToggle} />
        {actions && <div className="flex shrink-0 items-center gap-0.5">{actions}</div>}
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="list"
            id={listId}
            ref={listRef}
            onScroll={onScroll}
            data-motion="section-list"
            className={cn('overflow-y-auto', listClassName)}
            layoutScroll
            {...sectionListMotion(reduceMotion)}
          >
            {children}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

/** A section's rows: they fade in on a stagger and slide out on removal. */
export function SidebarSectionRows({ children }: { children: ReactNode }) {
  return (
    <ul className="flex flex-col">
      <AnimatePresence>{children}</AnimatePresence>
    </ul>
  );
}
