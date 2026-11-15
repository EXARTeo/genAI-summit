import { lazy, type ComponentType } from 'react';

const KEY = 'mnamon:chunk-reload';

/**
 * `React.lazy` that survives a redeploy: a tab opened on the old build asks for chunk files the
 * new build replaced ("Failed to fetch dynamically imported module"). Reload the page once to get
 * the new build; a second failure in a row is a real error and reaches the error boundary.
 */
export function lazyPage<T extends ComponentType<unknown>>(load: () => Promise<{ default: T }>) {
  return lazy(async () => {
    try {
      const mod = await load();
      safeStorage(() => sessionStorage.removeItem(KEY));
      return mod;
    } catch (error) {
      const reloaded = safeStorage(() => sessionStorage.getItem(KEY)) === '1';
      if (!reloaded && isChunkError(error)) {
        safeStorage(() => sessionStorage.setItem(KEY, '1'));
        window.location.reload();
        return new Promise<never>(() => {}); // the reload replaces the page
      }
      throw error;
    }
  });
}

export function isChunkError(error: unknown): boolean {
  const msg = error instanceof Error ? error.message : String(error);
  return /dynamically imported module|Importing a module script failed|error loading dynamically imported module/i.test(
    msg,
  );
}

function safeStorage<T>(fn: () => T): T | undefined {
  try {
    return fn();
  } catch {
    return undefined;
  }
}
