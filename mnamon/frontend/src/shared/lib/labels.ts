// Human labels for ids. The UI never prints raw UUIDs or hashes: audits show their readable id
// (`SYS-002-20261115-0930`) or "<system> · <started>", actors show a role, hashes are hidden.

/** `SYS-002-20261115-0930`: the readable audit id the backend now generates. */
const READABLE_AUDIT = /^[A-Z][A-Z0-9]*-\d+-\d{8}-\d{4}$/;
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
const HEX = /\b[0-9a-f]{16,}\b/i;

/** True for strings that are or contain a UUID / long hex hash / `sha256:` digest. */
export function isHashLike(s: string | null | undefined): boolean {
  return !!s && (UUID.test(s) || HEX.test(s) || /sha256:/i.test(s));
}

export function formatStarted(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** An audit's label: its readable id, else "<SYSTEM_ID> · <started>". */
export function auditLabel(a: { id: string; systemId: string; createdAt?: string | null }): string {
  if (READABLE_AUDIT.test(a.id)) return a.id;
  const when = formatStarted(a.createdAt);
  return when ? `${a.systemId} · ${when}` : a.systemId;
}

/** "client:<uuid>" -> "Engineer", "agent:audit-pipeline" -> "audit-pipeline agent". */
export function actorLabel(actor: string | null | undefined): string {
  if (!actor) return '–';
  const [kind, ...rest] = actor.split(':');
  const name = rest.join(':');
  if (kind === 'client' || kind === 'engineer' || kind === 'user') {
    return !name || isHashLike(name) ? 'Engineer' : name;
  }
  if (kind === 'agent') return name && !isHashLike(name) ? `${name} agent` : 'Agent';
  return isHashLike(actor) ? 'Someone' : actor;
}
