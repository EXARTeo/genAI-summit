// Git-style diff helpers for the change inbox and the source reader: a line diff (LCS) with line
// numbers, a unified-diff parser, word-level highlights on paired lines and the split-view pairing.
import type { DiffRow, WordPart } from './types';

type Op<T> = { op: 'eq' | 'del' | 'add'; a?: T; b?: T };

/** Longest-common-subsequence edit script; falls back to "all removed, all added" when too big. */
export function lcsOps<T>(a: T[], b: T[], max = 4_000_000): Op<T>[] {
  const n = a.length;
  const m = b.length;
  if (n * m > max) {
    return [...a.map((x) => ({ op: 'del' as const, a: x })), ...b.map((y) => ({ op: 'add' as const, b: y }))];
  }
  const dp: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: Op<T>[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ op: 'eq', a: a[i], b: b[j] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ op: 'del', a: a[i++] });
    } else {
      out.push({ op: 'add', b: b[j++] });
    }
  }
  while (i < n) out.push({ op: 'del', a: a[i++] });
  while (j < m) out.push({ op: 'add', b: b[j++] });
  return out;
}

const lines = (t: string) => (t === '' ? [] : t.replace(/\r\n/g, '\n').split('\n'));

/** Full line diff of two texts, with old/new line numbers and word highlights. */
export function lineDiff(oldText: string, newText: string): DiffRow[] {
  let o = 0;
  let n = 0;
  const rows: DiffRow[] = lcsOps(lines(oldText), lines(newText)).map((op) => {
    if (op.op === 'eq') return { type: 'ctx', text: op.a!, oldNo: ++o, newNo: ++n };
    if (op.op === 'del') return { type: 'del', text: op.a!, oldNo: ++o };
    return { type: 'add', text: op.b!, newNo: ++n };
  });
  return withWordHighlights(rows);
}

/** Keep `context` unchanged lines around each change; longer unchanged runs become a hunk row. */
export function collapseContext(rows: DiffRow[], context = 3): DiffRow[] {
  const changed = rows.map((r) => r.type === 'add' || r.type === 'del');
  if (!changed.some(Boolean)) return rows;
  const keep = rows.map((_, i) => {
    for (let k = Math.max(0, i - context); k <= Math.min(rows.length - 1, i + context); k++) {
      if (changed[k]) return true;
    }
    return false;
  });
  const out: DiffRow[] = [];
  let skipped = 0;
  rows.forEach((r, i) => {
    if (keep[i] || r.type === 'hunk') {
      if (skipped > 0) out.push({ type: 'hunk', text: `${skipped} unchanged line${skipped > 1 ? 's' : ''}` });
      skipped = 0;
      out.push(r);
    } else {
      skipped++;
    }
  });
  if (skipped > 0) out.push({ type: 'hunk', text: `${skipped} unchanged line${skipped > 1 ? 's' : ''}` });
  return out;
}

/** Parse a unified diff (backend `difflib` output) into numbered rows; file headers are dropped. */
export function parseUnified(diff: string): DiffRow[] {
  const rows: DiffRow[] = [];
  let o = 0;
  let n = 0;
  for (const raw of diff.replace(/\r\n/g, '\n').replace(/\n$/, '').split('\n')) {
    if (raw.startsWith('+++') || raw.startsWith('---')) continue;
    const h = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/.exec(raw);
    if (h) {
      o = Number(h[1]) - 1;
      n = Number(h[2]) - 1;
      rows.push({ type: 'hunk', text: raw });
      continue;
    }
    if (raw.startsWith('\\')) continue; // "\ No newline at end of file"
    if (raw.startsWith('+')) rows.push({ type: 'add', text: raw.slice(1), newNo: ++n });
    else if (raw.startsWith('-')) rows.push({ type: 'del', text: raw.slice(1), oldNo: ++o });
    // An empty line inside a hunk is a blank context line whose leading space was trimmed.
    else if (raw.startsWith(' ') || (raw === '' && rows.length > 0)) {
      rows.push({ type: 'ctx', text: raw.slice(1), oldNo: ++o, newNo: ++n });
    }
  }
  return withWordHighlights(rows);
}

const tokens = (s: string) => s.split(/(\s+)/).filter((t) => t !== '');

/** Word diff of one removed/added line pair. */
export function wordDiff(a: string, b: string): { old: WordPart[]; new: WordPart[] } | null {
  const ta = tokens(a);
  const tb = tokens(b);
  if (ta.length * tb.length > 250_000) return null;
  const old: WordPart[] = [];
  const neu: WordPart[] = [];
  for (const op of lcsOps(ta, tb)) {
    if (op.op === 'eq') {
      old.push({ text: op.a!, changed: false });
      neu.push({ text: op.b!, changed: false });
    } else if (op.op === 'del') old.push({ text: op.a!, changed: true });
    else neu.push({ text: op.b!, changed: true });
  }
  // Mostly rewritten lines read better without word marks.
  const kept = old.filter((p) => !p.changed && p.text.trim()).length;
  if (kept === 0) return null;
  return { old: merge(old), new: merge(neu) };
}

function merge(parts: WordPart[]): WordPart[] {
  const out: WordPart[] = [];
  for (const p of parts) {
    const last = out[out.length - 1];
    if (last && last.changed === p.changed) last.text += p.text;
    else out.push({ ...p });
  }
  return out;
}

/** Pair each run of removed lines with the run of added lines right after it, word-diffing pairs. */
export function withWordHighlights(rows: DiffRow[]): DiffRow[] {
  const out = rows.map((r) => ({ ...r }));
  let i = 0;
  while (i < out.length) {
    if (out[i].type !== 'del') {
      i++;
      continue;
    }
    const delStart = i;
    while (i < out.length && out[i].type === 'del') i++;
    const addStart = i;
    while (i < out.length && out[i].type === 'add') i++;
    const pairs = Math.min(addStart - delStart, i - addStart);
    for (let k = 0; k < pairs; k++) {
      const d = out[delStart + k];
      const a = out[addStart + k];
      const w = wordDiff(d.text, a.text);
      if (w) {
        d.words = w.old;
        a.words = w.new;
      }
    }
  }
  return out;
}

export function diffCounts(rows: DiffRow[]): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const r of rows) {
    if (r.type === 'add') added++;
    else if (r.type === 'del') removed++;
  }
  return { added, removed };
}

export type SplitRow = { hunk: DiffRow } | { left: DiffRow | null; right: DiffRow | null };

/** Rows for a side-by-side view: context on both sides, removed left, added right. */
export function toSplit(rows: DiffRow[]): SplitRow[] {
  const out: SplitRow[] = [];
  let i = 0;
  while (i < rows.length) {
    const r = rows[i];
    if (r.type === 'hunk') {
      out.push({ hunk: r });
      i++;
    } else if (r.type === 'ctx') {
      out.push({ left: r, right: r });
      i++;
    } else {
      const dels: DiffRow[] = [];
      const adds: DiffRow[] = [];
      while (i < rows.length && rows[i].type === 'del') dels.push(rows[i++]);
      while (i < rows.length && rows[i].type === 'add') adds.push(rows[i++]);
      for (let k = 0; k < Math.max(dels.length, adds.length); k++) {
        out.push({ left: dels[k] ?? null, right: adds[k] ?? null });
      }
    }
  }
  return out;
}
