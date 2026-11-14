/**
 * The conversation list's motion (magenticx `features/chat/lib/sidebarMotion.ts`), adapted to the
 * Mnamon motion rules (docs/services/frontend.md, "Motion"): ease-out tweens, no springs, 4 px at
 * most, transform and opacity only, instant under reduced motion.
 */
import { easeOut } from '@/shared/lib/motion';

/** The selected row's highlight: one layoutId across Pinned and Chats, so it glides between them. */
export const SIDEBAR_ROW_LAYOUT_ID = 'chat-sidebar-active-row';

/** Rows sliding to a new place (a pin, a chat moving to the top). */
export const ROW_GLIDE = { type: 'tween', duration: 0.22, ease: easeOut } as const;

/** Fade-and-drop for a section's list as it unfolds. */
export const sectionListMotion = (reduceMotion: boolean | null) => ({
  initial: reduceMotion ? { opacity: 0 } : { opacity: 0, y: -4 },
  animate: { opacity: 1, y: 0 },
  exit: reduceMotion
    ? { opacity: 0, transition: { duration: 0 } }
    : { opacity: 0, y: -4, transition: { duration: 0.12, ease: 'easeIn' as const } },
  transition: reduceMotion ? { duration: 0 } : { duration: 0.18, ease: easeOut },
});

/** A list row: fades and rises in on a short stagger, slides out to the left. */
export const rowMotion = (reduceMotion: boolean | null, index: number) => ({
  layout: 'position' as const,
  initial: reduceMotion ? { opacity: 0 } : { opacity: 0, y: 4 },
  animate: { opacity: 1, y: 0 },
  exit: reduceMotion
    ? { opacity: 0, transition: { duration: 0 } }
    : { opacity: 0, x: -4, transition: { duration: 0.15, ease: 'easeIn' as const } },
  transition: reduceMotion
    ? { duration: 0 }
    : {
        opacity: { duration: 0.22, delay: Math.min(index * 0.025, 0.3) },
        y: { duration: 0.22, delay: Math.min(index * 0.025, 0.3) },
        layout: ROW_GLIDE,
      },
});
