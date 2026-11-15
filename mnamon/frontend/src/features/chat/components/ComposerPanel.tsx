/**
 * The shell of the panels that open from the composer's control row: the agent map and the plan
 * (port of magenticx `features/chat/components/ComposerPanel.tsx`). On a desktop it is a large
 * modal centred on the whole viewport (`min(1200px, 92vw)` x `min(820px, 88vh)`, a shorter card
 * while there is nothing to show), with the scrim over the sidebar too, so the tree and the flow
 * graph have room; on a phone it is a bottom sheet. Modal (a Radix dialog): Esc or a click outside
 * closes it and focus stays inside. What goes inside (a header, the scrolling views) is the
 * panel's own.
 */
import * as DialogPrimitive from '@radix-ui/react-dialog';
import type { ReactNode, Ref, RefObject } from 'react';
import { useMediaQuery } from '@/shared/hooks/useMediaQuery';
import { cn } from '@/shared/lib/utils';

export interface ComposerPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The button the panel opens from (focus goes back to it on close). */
  anchorRef: RefObject<HTMLElement>;
  /** Nothing to show yet: a smaller card on a desktop. */
  compact?: boolean;
  /** For the opening button's `aria-controls`. */
  id?: string;
  contentRef?: Ref<HTMLDivElement>;
  onOpenAutoFocus?: (event: Event) => void;
  onEscapeKeyDown?: (event: KeyboardEvent) => void;
  children: ReactNode;
}

export function ComposerPanel({
  open,
  onOpenChange,
  compact = false,
  id,
  contentRef,
  onOpenAutoFocus,
  onEscapeKeyDown,
  children,
}: ComposerPanelProps) {
  const isMobile = !useMediaQuery('(min-width: 640px)');

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[60] bg-scrim data-[state=open]:animate-[overlay-in_180ms_ease-out] sm:backdrop-blur-[2px]" />
        <DialogPrimitive.Content
          ref={contentRef}
          id={id}
          aria-describedby={undefined}
          onOpenAutoFocus={onOpenAutoFocus}
          onEscapeKeyDown={onEscapeKeyDown}
          className={cn(
            'fixed z-[60] flex flex-col overflow-hidden border border-border/70 bg-surface text-text shadow-pop focus:outline-none',
            isMobile
              ? 'composer-sheet inset-x-0 bottom-0 h-[85dvh] rounded-t-[1.5rem] border-b-0'
              : cn(
                  // Centred without a transform, so the entrance animation can own `transform`.
                  'composer-panel inset-0 m-auto rounded-[1.5rem]',
                  compact
                    ? 'h-[min(440px,88vh)] w-[min(640px,92vw)]'
                    : 'h-[min(820px,88vh)] w-[min(1200px,92vw)]',
                ),
          )}
        >
          {isMobile ? (
            <div className="relative mx-auto mt-2.5 h-1 w-10 shrink-0 rounded-full bg-muted/25" />
          ) : null}
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
