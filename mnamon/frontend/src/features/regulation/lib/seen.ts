// "Seen" state of the change inbox, per browser (localStorage). A change is new until it is opened;
// each file (provision diff) inside it is new until it is expanded. Storage failures are ignored:
// the inbox then simply shows everything as new for this session.
const KEY = 'mnamon.regulation.seen.v1';

export interface SeenState {
  changes: Record<string, true>;
  files: Record<string, true>;
}

let state: SeenState = load();
const listeners = new Set<() => void>();

function load(): SeenState {
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed = raw ? (JSON.parse(raw) as Partial<SeenState>) : {};
    return { changes: parsed.changes ?? {}, files: parsed.files ?? {} };
  } catch {
    return { changes: {}, files: {} };
  }
}

function save(next: SeenState) {
  state = next;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // private mode / quota: keep the in-memory state only
  }
  listeners.forEach((l) => l());
}

export const fileKey = (changeId: string, fileKey: string) => `${changeId}::${fileKey}`;

export const seenStore = {
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  get: (): SeenState => state,
  markChange(changeId: string) {
    if (state.changes[changeId]) return;
    save({ ...state, changes: { ...state.changes, [changeId]: true } });
  },
  markFile(changeId: string, key: string) {
    const k = fileKey(changeId, key);
    if (state.files[k] && state.changes[changeId]) return;
    save({ changes: { ...state.changes, [changeId]: true }, files: { ...state.files, [k]: true } });
  },
  markAll(changeIds: string[]) {
    const changes = { ...state.changes };
    for (const id of changeIds) changes[id] = true;
    save({ ...state, changes });
  },
};
