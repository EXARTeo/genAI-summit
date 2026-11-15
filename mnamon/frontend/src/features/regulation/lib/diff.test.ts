import { describe, expect, it } from 'vitest';
import { collapseContext, diffCounts, lineDiff, parseUnified, toSplit } from './diff';
import { changeFiles, parentKb, provisionLabel, topProvisionId } from './regulation';
import { mockDocDiff, mockReleases } from './mocks';

describe('line diff', () => {
  it('numbers lines and marks changed words on paired lines', () => {
    const rows = lineDiff('a\nthe quick fox\nc', 'a\nthe slow fox\nc\nd');
    expect(diffCounts(rows)).toEqual({ added: 2, removed: 1 });
    const del = rows.find((r) => r.type === 'del')!;
    const add = rows.find((r) => r.type === 'add')!;
    expect(del.oldNo).toBe(2);
    expect(add.newNo).toBe(2);
    expect(del.words?.filter((w) => w.changed).map((w) => w.text.trim())).toEqual(['quick']);
    expect(add.words?.filter((w) => w.changed).map((w) => w.text.trim())).toEqual(['slow']);
  });

  it('treats a missing side as fully added or removed', () => {
    expect(diffCounts(lineDiff('', 'x\ny'))).toEqual({ added: 2, removed: 0 });
    expect(diffCounts(lineDiff('x', ''))).toEqual({ added: 0, removed: 1 });
  });

  it('collapses long unchanged runs into hunk rows', () => {
    const old = Array.from({ length: 20 }, (_, i) => `l${i}`).join('\n');
    const neu = old.replace('l10', 'L10');
    const rows = collapseContext(lineDiff(old, neu), 2);
    expect(rows.filter((r) => r.type === 'hunk').map((r) => r.text)).toEqual([
      '8 unchanged lines',
      '7 unchanged lines',
    ]);
  });

  it('parses a unified diff with line numbers and pairs rows for the split view', () => {
    const rows = parseUnified(mockDocDiff('x').unified);
    expect(rows[0].type).toBe('hunk');
    const firstDel = rows.find((r) => r.type === 'del')!;
    expect(firstDel.oldNo).toBe(16);
    const split = toSplit(rows);
    expect(split.some((r) => 'left' in r && r.left?.type === 'del' && r.right?.type === 'add')).toBe(true);
  });
});

describe('change files', () => {
  it('keeps provisions as files and folds interpretation nodes into the document diff', () => {
    const files = changeFiles({
      provisions: ['AIA.10.5', 'INT.guide.4-bias'],
      sourceId: 'guide',
      fromVersion: 1,
      toVersion: 2,
    });
    expect(files.map((f) => f.kind)).toEqual(['document', 'provision']);
  });

  it('finds the base kb of a candidate and labels provisions', () => {
    expect(parentKb(mockReleases(), '2026.11.15-1')).toBe('2026.11.14-2');
    expect(parentKb(mockReleases(), 'nope')).toBeNull();
    expect(provisionLabel('AIA.10.2.f')).toBe('Art. 10(2)(f)');
    expect(provisionLabel('AIA.ANNEX_III')).toBe('Annex III');
    expect(topProvisionId('AIA.10.2.f')).toBe('AIA.10');
    expect(topProvisionId('AIA.REC.12')).toBe('AIA.REC.12');
  });
});
