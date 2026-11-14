import { useEffect } from 'react';
import { useThemeStore } from '@/shared/stores/theme';

/** Theme preference + setter; follows OS changes while on `system`. */
export function useTheme() {
  const { preference, resolved, setPreference, syncSystem } = useThemeStore();

  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!mq) return;
    const onChange = () => syncSystem();
    mq.addEventListener?.('change', onChange);
    return () => mq.removeEventListener?.('change', onChange);
  }, [syncSystem]);

  return { preference, resolved, setPreference };
}
