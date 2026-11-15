import { useCallback, useLayoutEffect, useState } from 'react';

/**
 * Height that takes an element from where it starts to the bottom of the window (`bottom` px
 * kept free), at least `min`. `ref` is a callback ref, so it measures when the element mounts
 * (pages show a skeleton first) and again on every window resize.
 */
export function useFillHeight<T extends HTMLElement>(min = 480, bottom = 32) {
  const [el, setEl] = useState<T | null>(null);
  const [height, setHeight] = useState<number | undefined>(undefined);
  const ref = useCallback((node: T | null) => setEl(node), []);
  useLayoutEffect(() => {
    if (!el) return;
    const measure = () => {
      // Measured from the scroll container's top, so a scrolled page gives the same answer.
      const scroller = el.closest('[data-testid="main-card"]');
      const top = el.getBoundingClientRect().top + (scroller?.scrollTop ?? 0);
      setHeight(Math.max(min, Math.round(window.innerHeight - top - bottom)));
    };
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [el, min, bottom]);
  return { ref, height };
}
