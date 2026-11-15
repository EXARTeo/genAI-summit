import { useSyncExternalStore } from 'react';
import { fileKey, seenStore, type SeenState } from '../lib/seen';
import { changeFiles } from '../lib/regulation';
import type { RegChange } from '../lib/types';

/** The browser's seen state of the change inbox (re-renders on every mark). */
export function useSeen(): SeenState {
  return useSyncExternalStore(seenStore.subscribe, seenStore.get, seenStore.get);
}

/** Unread counts: changes never opened, and per change the files never expanded. */
export function useUnread(changes: RegChange[] | undefined) {
  const seen = useSeen();
  const list = changes ?? [];
  const isNewChange = (c: RegChange) => !seen.changes[c.id];
  const newFiles = (c: RegChange) => changeFiles(c).filter((f) => !seen.files[fileKey(c.id, f.key)]).length;
  return {
    seen,
    isNewChange,
    newFiles,
    isNewFile: (changeId: string, key: string) => !seen.files[fileKey(changeId, key)],
    unreadCount: list.filter(isNewChange).length,
  };
}
