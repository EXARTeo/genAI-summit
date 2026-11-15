import { useCallback, useLayoutEffect, useState } from 'react';

/** An element's height, kept current (ResizeObserver); `ref` is a callback ref, so it also measures an element that mounts late. */
export function useElementHeight<T extends HTMLElement>() {
  const [el, setEl] = useState<T | null>(null);
  const [height, setHeight] = useState(0);
  const ref = useCallback((node: T | null) => setEl(node), []);
  useLayoutEffect(() => {
    if (!el) return;
    const measure = () => setHeight(Math.round(el.getBoundingClientRect().height));
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return { ref, height };
}
