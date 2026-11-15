/**
 * The shell of the panels that open from the composer's control row: the agent map and the plan
 * (port of magenticx `features/chat/components/ComposerPanel.tsx`). On a desktop it floats above
 * the composer, as wide as the composer, rising out of it; on a phone it is a bottom sheet. Modal
 * (a Radix dialog): Esc or a click outside closes it and focus stays inside. What goes inside (a
 * header, the scrolling views) is the panel's own.
 */
import * as DialogPrimitive from '@radix-ui/react-dialog';
import {
  useLayoutEffect,
  useState,
  type CSSProperties,
  type ReactNode,
  type Ref,
  type RefObject,
} from 'react';
import { useMediaQuery } from '@/shared/hooks/useMediaQuery';
import { cn } from '@/shared/lib/utils';

const PANEL_GAP = 12;
const PANEL_MIN_HEIGHT = 300;
const PANEL_MAX_HEIGHT = 640;
/** A panel with nothing to show yet: a calm, shorter card. */
const COMPACT_HEIGHT = 380;
// Room left above the panel for the top bar.
const HEADER_ROOM = 76;

interface Placement {
  left: number;
  width: number;
  bottom: number;
  height: number;
}

/** Above the composer the button sits in, as wide as it, as tall as fits. */
function placeAbove(anchor: HTMLElement | null): Placement | null {
  if (!anchor) return null;
  const shell = (anchor.closest('[data-composer-shell]') as HTMLElement | null) ?? anchor;
  const rect = shell.getBoundingClientRect();
  const viewport = window.innerWidth;
  const width = Math.min(Math.max(rect.width, 480), viewport - 32);
  const left = Math.min(Math.max(rect.left + rect.width / 2 - width / 2, 16), viewport - width - 16);
  const room = rect.top - PANEL_GAP - HEADER_ROOM;
  const height = Math.min(Math.max(room, PANEL_MIN_HEIGHT), PANEL_MAX_HEIGHT);
  return { left, width, bottom: window.innerHeight - rect.top + PANEL_GAP, height };
}

export interface ComposerPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The button the panel opens from; the panel sits above its composer. */
  anchorRef: RefObject<HTMLElement>;
  /** Nothing to show yet: a shorter card on a desktop. */
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
  anchorRef,
  compact = false,
  id,
  contentRef,
  onOpenAutoFocus,
  onEscapeKeyDown,
  children,
}: ComposerPanelProps) {
  const isMobile = !useMediaQuery('(min-width: 640px)');
  const [placement, setPlacement] = useState<Placement | null>(null);

  useLayoutEffect(() => {
    if (!open || isMobile) return;
    const place = () => setPlacement(placeAbove(anchorRef.current));
    place();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [open, isMobile, anchorRef]);

  const desktopStyle: CSSProperties | undefined =
    !isMobile && placement
      ? {
          left: placement.left,
          width: placement.width,
          bottom: placement.bottom,
          height: compact ? Math.min(placement.height, COMPACT_HEIGHT) : placement.height,
        }
      : undefined;

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          className={cn(
            'fixed inset-0 z-[60] data-[state=open]:animate-[overlay-in_180ms_ease-out]',
            isMobile ? 'bg-scrim' : 'bg-background/40 backdrop-blur-[2px]',
          )}
        />
        <DialogPrimitive.Content
          ref={contentRef}
          id={id}
          aria-describedby={undefined}
          onOpenAutoFocus={onOpenAutoFocus}
          onEscapeKeyDown={onEscapeKeyDown}
          style={desktopStyle}
          className={cn(
            'fixed z-[60] flex flex-col overflow-hidden border border-border/70 bg-surface text-text shadow-pop focus:outline-none',
            isMobile
              ? 'composer-sheet inset-x-0 bottom-0 h-[85dvh] rounded-t-[1.5rem] border-b-0'
              : 'composer-panel rounded-[1.5rem]',
            !isMobile && !placement && 'invisible',
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
