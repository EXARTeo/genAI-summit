import { useCallback, useLayoutEffect, useState } from 'react';

/**
 * Height that lets an element reach the bottom of the window from where it starts, at least
 * `min` px; `bottom` = space kept below it. `ref` is a callback ref, so it measures when the
 * element appears (a page that first renders a skeleton mounts it later) and on resize.
 */
export function useFillHeight<T extends HTMLElement>(min = 560, bottom = 32) {
  const [el, setEl] = useState<T | null>(null);
  const [height, setHeight] = useState(min);
  const ref = useCallback((node: T | null) => setEl(node), []);
  useLayoutEffect(() => {
    if (!el) return;
    const measure = () => {
      const top = el.getBoundingClientRect().top;
      setHeight(Math.max(min, Math.round(window.innerHeight - top - bottom)));
    };
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [el, min, bottom]);
  return { ref, height };
}
