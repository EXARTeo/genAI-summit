/**
 * Motion system (JS half): framer-motion variants shared by every feature.
 * CSS half: src/styles/motion.css. Keep it subtle: short distances, <= 0.4 s,
 * never block input. framer-motion honours prefers-reduced-motion through
 * <MotionConfig reducedMotion="user"> in main.tsx.
 */
import type { Transition, Variants } from 'framer-motion';

export const easeOut = [0.16, 1, 0.3, 1] as const;

export const spring: Transition = { type: 'spring', stiffness: 380, damping: 32, mass: 0.8 };

export const durations = { fast: 0.12, base: 0.2, slow: 0.36 } as const;

/** Route change: fade + small rise. Use with <AnimatePresence mode="wait">. */
export const pageTransition: Variants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: { duration: durations.slow, ease: easeOut } },
  exit: { opacity: 0, y: -4, transition: { duration: durations.fast, ease: 'easeIn' } },
};

/** Parent of a staggered list. Children use `listItem`. */
export const staggerList = (stagger = 0.045, delay = 0.02): Variants => ({
  initial: {},
  animate: { transition: { staggerChildren: stagger, delayChildren: delay } },
});

export const listItem: Variants = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0, transition: { duration: durations.slow, ease: easeOut } },
  exit: { opacity: 0, transition: { duration: durations.fast } },
};

export const fadeIn: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: { duration: durations.base } },
  exit: { opacity: 0, transition: { duration: durations.fast } },
};

export const scaleIn: Variants = {
  initial: { opacity: 0, scale: 0.96 },
  animate: { opacity: 1, scale: 1, transition: spring },
  exit: { opacity: 0, scale: 0.98, transition: { duration: durations.fast } },
};

/** Card hover lift (when CSS `.hover-lift` is not enough, e.g. for layout animations). */
export const hoverLift = {
  whileHover: { y: -2, transition: { duration: durations.base, ease: easeOut } },
  whileTap: { scale: 0.99 },
};

/** Step-complete check: animate `pathLength` from 0 to 1. */
export const checkDraw: Variants = {
  initial: { pathLength: 0, opacity: 0 },
  animate: { pathLength: 1, opacity: 1, transition: { duration: 0.38, ease: easeOut, delay: 0.06 } },
};

/** Waiting-for-a-human pulse (also available as CSS `.approval-pulse`). */
export const approvalPulse: Variants = {
  animate: {
    scale: [1, 1.04, 1],
    transition: { duration: 2, repeat: Infinity, ease: 'easeInOut' },
  },
};

/** Collapsible panels (sidebar, accordions). */
export const collapse: Variants = {
  initial: { height: 0, opacity: 0 },
  animate: { height: 'auto', opacity: 1, transition: { duration: durations.base, ease: easeOut } },
  exit: { height: 0, opacity: 0, transition: { duration: durations.fast } },
};
