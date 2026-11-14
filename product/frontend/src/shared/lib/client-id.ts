/**
 * The anonymous caller id the backend expects in `X-Client-Id` (no login).
 * Generated once per browser and kept in localStorage. Not authentication.
 */
export const CLIENT_ID_STORAGE_KEY = 'aac.clientId';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

let memoryFallback: string | null = null;

function newUuid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  // RFC 4122 v4 fallback for old browsers / non-secure contexts.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export function getClientId(): string {
  try {
    const stored = localStorage.getItem(CLIENT_ID_STORAGE_KEY);
    if (stored && UUID_RE.test(stored)) return stored;
    const id = newUuid();
    localStorage.setItem(CLIENT_ID_STORAGE_KEY, id);
    return id;
  } catch {
    memoryFallback ??= newUuid();
    return memoryFallback;
  }
}
