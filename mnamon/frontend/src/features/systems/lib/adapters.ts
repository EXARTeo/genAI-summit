// Maps the backend SystemOut onto the UI System. The backend keeps the seeded system card
// under `data.card` (plus `data.source`, ...); the UI reads the card fields flat from
// `system.data`. Flat data (mocks, older rows) passes through unchanged.
import type { System, SystemCard } from './types';

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);

export function toSystem(raw: System): System {
  const data: Record<string, unknown> = isObj(raw?.data) ? raw.data : {};
  const { card, ...rest } = data;
  const merged = (isObj(card) ? { ...card, ...rest } : rest) as SystemCard;
  return { ...raw, name: raw.name ?? (merged.name as string | undefined) ?? raw.id, data: merged };
}

export function toSystems(raw: System[]): System[] {
  return Array.isArray(raw) ? raw.map(toSystem) : [];
}

interface AuditRow {
  id: string;
  systemId: string;
  status: string;
  updatedAt: string;
  data: Record<string, unknown>;
}

/**
 * Fill `last_audit` from the audits list when the backend does not send one: the newest
 * audit per system, its status (`waiting_approval` reads as `awaiting_approval`) and, once
 * finished, the verdict counts the pipeline stores in `data.verdicts`.
 */
export function withLastAudits(systems: System[], audits: AuditRow[]): System[] {
  const latest = new Map<string, AuditRow>();
  for (const a of audits) {
    const prev = latest.get(a.systemId);
    if (!prev || a.updatedAt > prev.updatedAt) latest.set(a.systemId, a);
  }
  return systems.map((s) => {
    const a = latest.get(s.id);
    if (s.data.last_audit || !a) return s;
    const v = isObj(a.data.verdicts) ? a.data.verdicts : null;
    const n = (k: string) => (v && typeof v[k] === 'number' ? (v[k] as number) : 0);
    return {
      ...s,
      data: {
        ...s.data,
        last_audit: {
          id: a.id,
          status: a.status === 'waiting_approval' ? 'awaiting_approval' : a.status,
          at: a.updatedAt,
          // The obligation pipeline counts `gap` / `pass`; older runs `indicates_gap` / `supports_compliance`.
          findings: v
            ? {
                gaps: n('gap') + n('indicates_gap'),
                supports: n('pass') + n('supports_compliance'),
                inconclusive: n('inconclusive'),
              }
            : undefined,
        },
      },
    };
  });
}
