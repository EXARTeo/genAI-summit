// Source reader logic: source grouping for the grid, the provision outline (chapters → articles →
// paragraphs/points) from reg-memory, and the heading/page split used when a source has none.
import type { Provision, ReaderBlock, ReaderSection, RegSource, SourceKind } from './types';

export interface SourceGroup {
  key: string;
  label: string;
  blurb: string;
  kinds: SourceKind[];
}

export const SOURCE_GROUPS: SourceGroup[] = [
  {
    key: 'law',
    label: 'Law',
    blurb: 'Regulations, consolidated texts and national law',
    kinds: ['regulation', 'consolidated', 'national_law'],
  },
  { key: 'amendment', label: 'Amendments', blurb: 'Acts that change the law', kinds: ['amendment'] },
  { key: 'guideline', label: 'Guidelines', blurb: 'Commission guidance and templates', kinds: ['guideline'] },
  {
    key: 'code',
    label: 'Codes of practice',
    blurb: 'Voluntary codes and their chapters',
    kinds: ['code_of_practice'],
  },
  { key: 'faq', label: 'FAQs', blurb: 'Questions and answers', kinds: ['faq'] },
  { key: 'standard', label: 'Standards', blurb: 'Harmonised standards work', kinds: ['standard'] },
  {
    key: 'internal',
    label: 'Internal policy',
    blurb: "The organisation's own rules",
    kinds: ['internal_policy'],
  },
  { key: 'other', label: 'Other', blurb: 'Policy pages, communications, indexes', kinds: ['other'] },
];

export const KIND_LABEL: Record<SourceKind, string> = {
  regulation: 'Regulation',
  amendment: 'Amendment',
  consolidated: 'Consolidated text',
  guideline: 'Guideline',
  faq: 'FAQ',
  code_of_practice: 'Code of practice',
  standard: 'Standard',
  national_law: 'National law',
  internal_policy: 'Internal policy',
  other: 'Other',
};

export function groupOf(kind: SourceKind): SourceGroup {
  return SOURCE_GROUPS.find((g) => g.kinds.includes(kind)) ?? SOURCE_GROUPS[SOURCE_GROUPS.length - 1];
}

/** Sources bucketed by group (in SOURCE_GROUPS order); binding first, then the catalog's own order. */
export function groupSources(sources: RegSource[]): { group: SourceGroup; items: RegSource[] }[] {
  return SOURCE_GROUPS.map((group) => ({
    group,
    items: sources
      .filter((s) => groupOf(s.kind).key === group.key)
      .sort((a, b) => Number(b.binding === true) - Number(a.binding === true)),
  })).filter((g) => g.items.length > 0);
}

export function matchesSource(s: RegSource, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return [s.title, s.publisher, s.id, KIND_LABEL[s.kind], ...s.tags].some((v) =>
    v.toLowerCase().includes(needle),
  );
}

// ---- provisions → outline ---------------------------------------------------

const ROMAN: Record<string, number> = { I: 1, V: 5, X: 10, L: 50, C: 100 };

function roman(s: string): number | null {
  if (!/^[IVXLC]+$/.test(s)) return null;
  let total = 0;
  for (let i = 0; i < s.length; i++) {
    const v = ROMAN[s[i]];
    const next = ROMAN[s[i + 1]] ?? 0;
    total += v < next ? -v : v;
  }
  return total;
}

function segKey(seg: string): [number, number, string] {
  const r = /^ANNEX_([IVXLC]+)$/.exec(seg);
  if (r) return [1, roman(r[1]) ?? 0, ''];
  if (seg === 'REC') return [2, 0, ''];
  const m = /^(\d+)(.*)$/.exec(seg);
  if (m) return [0, Number(m[1]), m[2]];
  return [0, Number.MAX_SAFE_INTEGER, seg];
}

/** Natural order of provision ids: AIA.2 < AIA.10 < AIA.10a < AIA.ANNEX_I < AIA.ANNEX_IV. */
export function compareProvisionIds(a: string, b: string): number {
  const sa = a.split('.');
  const sb = b.split('.');
  for (let i = 0; i < Math.max(sa.length, sb.length); i++) {
    if (sa[i] === undefined) return -1;
    if (sb[i] === undefined) return 1;
    const [ga, na, ra] = segKey(sa[i]);
    const [gb, nb, rb] = segKey(sb[i]);
    if (ga !== gb) return ga - gb;
    if (na !== nb) return na - nb;
    if (ra !== rb) return ra.localeCompare(rb);
  }
  return 0;
}

/** "Art 10" → "Article 10"; other first path segments unchanged. */
export function provisionHeading(p: Pick<Provision, 'path' | 'id'>): string {
  const head = p.path[0] ?? p.id;
  return head.replace(/^Art\s+/, 'Article ');
}

/** The marker of a child block: "para 2" → "2.", "pt a" → "(a)", "pt 3" → "3.". */
export function segmentMarker(seg: string): string {
  const para = /^para\s+(.+)$/.exec(seg);
  if (para) return `${para[1]}.`;
  const pt = /^pt\s+(.+)$/.exec(seg);
  if (pt) return /^\d+$/.test(pt[1]) ? `${pt[1]}.` : `(${pt[1]})`;
  return seg;
}

/** A provision's own text without a leading line that repeats its title. */
export function ownText(p: Pick<Provision, 'text' | 'title'>): string {
  const text = (p.text ?? '').trim();
  if (!p.title) return text;
  const [first, ...rest] = text.split('\n');
  const norm = (s: string) =>
    s
      .replace(/['’\s]+$/g, '')
      .trim()
      .toLowerCase();
  return norm(first) === norm(p.title) ? rest.join('\n').trim() : text;
}

const sentenceCase = (s: string) => (s === s.toUpperCase() ? s.charAt(0) + s.slice(1).toLowerCase() : s);

/** A display title without stray trailing quotes from the parser. */
export function cleanTitle(t: string | null | undefined): string | null {
  return t ? t.replace(/['’]+$/, '').trim() : null;
}

/** The source's provisions as reader sections: one per article / annex / recital, children inline. */
export function provisionSections(items: Provision[]): ReaderSection[] {
  const ids = new Set(items.map((p) => p.id));
  const children = new Map<string, Provision[]>();
  const tops: Provision[] = [];
  for (const p of items) {
    if (p.parent && ids.has(p.parent)) {
      const list = children.get(p.parent) ?? [];
      list.push(p);
      children.set(p.parent, list);
    } else tops.push(p);
  }
  for (const list of children.values()) list.sort((a, b) => compareProvisionIds(a.id, b.id));
  tops.sort((a, b) => rankKind(a) - rankKind(b) || compareProvisionIds(a.id, b.id));

  const blocksOf = (p: Provision, depth: number, out: ReaderBlock[]) => {
    for (const c of children.get(p.id) ?? []) {
      out.push({ id: c.id, depth, marker: segmentMarker(c.path[c.path.length - 1] ?? ''), text: ownText(c) });
      blocksOf(c, depth + 1, out);
    }
  };

  return tops.map((p) => {
    const blocks: ReaderBlock[] = [];
    const own = ownText(p);
    if (own) blocks.push({ id: p.id, depth: 0, marker: '', text: own });
    blocksOf(p, 0, blocks);
    const { group, groupSub } = groupFor(p);
    return { key: p.id, label: provisionHeading(p), title: cleanTitle(p.title), group, groupSub, blocks };
  });
}

function rankKind(p: Provision): number {
  if (p.kind === 'recital') return 0;
  if (p.kind === 'annex') return 2;
  return 1;
}

function groupFor(p: Provision): { group: string; groupSub?: string | null } {
  if (p.kind === 'recital') {
    const n = Number(/\d+/.exec(p.path[0] ?? '')?.[0] ?? 0);
    const start = Math.floor((n - 1) / 25) * 25 + 1;
    return { group: `Recitals ${start}–${start + 24}` };
  }
  if (p.kind === 'annex') return { group: 'Annexes' };
  if (p.chapter)
    return {
      group: `Chapter ${p.chapter}`,
      groupSub: p.chapter_title ? sentenceCase(p.chapter_title) : null,
    };
  return { group: 'Articles' };
}

// ---- document text → sections (fallback) ---------------------------------------

const PAGE = /^<!--\s*page\s+(\d+)\s*-->$/i;
const MD_HEADING = /^(#{1,4})\s+(.+?)\s*#*$/;
// "2.1. Prohibitions listed in Article 5" — numbered headings in PDF text (not TOC lines with dot leaders).
const NUM_HEADING = /^(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+([A-ZͰ-Ͽ].{2,110})$/;

function clean(text: string): string {
  return text
    .split('\n')
    .filter((l) => !PAGE.test(l.trim()))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/** Split a document's text by markdown headings, else numbered headings, else pages, else whole. */
export function documentSections(text: string, title = 'Full text'): ReaderSection[] {
  const rows = text.replace(/\r\n/g, '\n').split('\n');
  const md = rows.filter((l) => MD_HEADING.test(l)).length;
  if (md >= 2)
    return splitBy(
      rows,
      (l) => {
        const m = MD_HEADING.exec(l);
        return m ? { label: m[2].replace(/\*\*/g, '').replace(/\s+/g, ' '), level: m[1].length } : null;
      },
      true,
      title,
    );

  const numbered = (l: string) => {
    const t = l.trim();
    if (/\.{4,}|…{2,}/.test(t)) return null;
    const m = NUM_HEADING.exec(t);
    return m ? { label: `${m[1]} ${m[2]}`.trim(), level: m[1].split('.').length } : null;
  };
  if (rows.filter((l) => numbered(l)).length >= 3) return splitBy(rows, numbered, false, title);

  const pages = rows.filter((l) => PAGE.test(l.trim())).length;
  if (pages >= 2) {
    return splitBy(
      rows,
      (l) => {
        const m = PAGE.exec(l.trim());
        return m ? { label: `Page ${m[1]}`, level: 1 } : null;
      },
      false,
      title,
    );
  }
  const body = clean(text);
  return body
    ? [
        {
          key: 'all',
          label: title,
          group: 'Document',
          blocks: [{ id: 'all', depth: 0, marker: '', text: body }],
        },
      ]
    : [];
}

function splitBy(
  rows: string[],
  heading: (l: string) => { label: string; level: number } | null,
  markdown: boolean,
  title: string,
): ReaderSection[] {
  const out: ReaderSection[] = [];
  let current: { label: string; level: number; lines: string[] } = { label: title, level: 0, lines: [] };
  let group = 'Document';
  const flush = () => {
    const body = clean(current.lines.join('\n'));
    if (!body && current.level === 0) return;
    // A table-of-contents entry: its "body" starts with a dot-leader / page-number line.
    const firstLine = body.split('\n')[0] ?? '';
    if (current.level > 0 && /^[\s.…·]{4,}\d*\s*$/.test(firstLine)) return;
    out.push({
      key: `s${out.length}`,
      label: current.label,
      group,
      blocks: body ? [{ id: `s${out.length}`, depth: 0, marker: '', text: body, markdown }] : [],
    });
  };
  for (const l of rows) {
    const h = heading(l);
    if (h) {
      flush();
      if (h.level <= 2 && markdown) group = h.label;
      current = { label: h.label, level: h.level, lines: [] };
    } else current.lines.push(l);
  }
  flush();
  // Heading-only sections (a chapter line right before its first article) carry no text.
  return out.filter((s) => s.blocks.length > 0);
}

/** Case-insensitive match in a section's label, title or text. */
export function sectionMatches(s: ReaderSection, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (needle.length < 2) return true;
  return (
    s.label.toLowerCase().includes(needle) ||
    (s.title ?? '').toLowerCase().includes(needle) ||
    s.blocks.some((b) => b.text.toLowerCase().includes(needle))
  );
}

/** Split text around matches of `q` for <mark> highlighting. */
export function highlightParts(text: string, q: string): { text: string; hit: boolean }[] {
  const needle = q.trim();
  if (needle.length < 2) return [{ text, hit: false }];
  const re = new RegExp(`(${needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
  return text
    .split(re)
    .filter((t) => t !== '')
    .map((t) => ({ text: t, hit: t.toLowerCase() === needle.toLowerCase() }));
}

/** "Article 10" → "Art. 10" for the outline. */
export const shortSectionLabel = (l: string) => l.replace(/^Article /, 'Art. ');
