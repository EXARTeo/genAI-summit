import { useEffect, useRef } from 'react';

/**
 * Global shortcut. `combo` like "mod+k" (mod = ⌘ on macOS, Ctrl elsewhere), "shift+?", "g".
 * Ignored while typing in inputs unless `allowInInputs`.
 */
export function useHotkey(combo: string, handler: (e: KeyboardEvent) => void, allowInInputs = false) {
  const ref = useRef(handler);
  ref.current = handler;

  useEffect(() => {
    const parts = combo.toLowerCase().split('+');
    const key = parts[parts.length - 1];
    const needMod = parts.includes('mod');
    const needShift = parts.includes('shift');
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing =
        target && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
      if (typing && !allowInInputs && !needMod) return;
      const mod = e.metaKey || e.ctrlKey;
      if (needMod !== mod || needShift !== e.shiftKey) return;
      if (e.key.toLowerCase() !== key) return;
      e.preventDefault();
      ref.current(e);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [combo, allowInInputs]);
}
