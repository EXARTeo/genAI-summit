/** Small formatters for a message's meta row (time, token counts, run duration). */

/** `14:05` (the user's locale decides 12 / 24 h), or '' for a missing or bad timestamp. */
export function formatClock(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/** 950 → `950`, 4200 → `4.2k`, 12000 → `12k`, 1250000 → `1.3M`. */
export function formatCompactTokens(n: number): string {
  if (!Number.isFinite(n) || n < 1000) return String(Math.max(0, Math.round(n || 0)));
  if (n < 1_000_000) {
    const k = n / 1000;
    return `${k < 10 ? k.toFixed(1).replace(/\.0$/, '') : Math.round(k)}k`;
  }
  const m = n / 1_000_000;
  return `${m < 10 ? m.toFixed(1).replace(/\.0$/, '') : Math.round(m)}M`;
}

/** Whole seconds between two ISO timestamps, or null when unknown or not positive. */
export function runSeconds(
  startedAt: string | null | undefined,
  completedAt: string | null | undefined,
): number | null {
  if (!startedAt || !completedAt) return null;
  const s = Math.round((Date.parse(completedAt) - Date.parse(startedAt)) / 1000);
  return Number.isFinite(s) && s > 0 ? s : null;
}

/** `42 s`, `3 min 5 s`, `2 min`. */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s ? `${m} min ${s} s` : `${m} min`;
}
