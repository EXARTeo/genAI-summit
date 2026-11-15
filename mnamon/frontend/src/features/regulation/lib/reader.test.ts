import { describe, expect, it } from 'vitest';
import { buildMockSources, mockProvisions } from './mocks';
import {
  compareProvisionIds,
  documentSections,
  groupSources,
  highlightParts,
  ownText,
  provisionSections,
  sectionMatches,
} from './reader';

describe('source grouping', () => {
  it('buckets sources by kind group, binding first', () => {
    const groups = groupSources(buildMockSources());
    expect(groups[0].group.key).toBe('law');
    expect(groups[0].items.every((s) => s.binding === true)).toBe(true);
    expect(groups.map((g) => g.group.key)).toContain('guideline');
  });
});

describe('provision outline', () => {
  it('orders ids naturally, annexes after articles', () => {
    const ids = ['AIA.ANNEX_IV', 'AIA.10', 'AIA.2', 'AIA.ANNEX_I', 'AIA.4a', 'AIA.4'];
    expect([...ids].sort(compareProvisionIds)).toEqual([
      'AIA.2',
      'AIA.4',
      'AIA.4a',
      'AIA.10',
      'AIA.ANNEX_I',
      'AIA.ANNEX_IV',
    ]);
  });

  it('builds one section per article with numbered child blocks', () => {
    const sections = provisionSections(mockProvisions().items);
    const art10 = sections.find((s) => s.key === 'AIA.10')!;
    expect(art10.label).toBe('Article 10');
    expect(art10.group).toBe('Chapter III');
    expect(art10.groupSub).toBe('High-risk ai systems');
    expect(art10.blocks.map((b) => [b.marker, b.depth])).toEqual([
      ['1.', 0],
      ['2.', 0],
      ['(f)', 1],
      ['5.', 0],
    ]);
  });

  it('drops a first line that repeats the title', () => {
    expect(ownText({ title: 'Scope', text: 'Scope\nThis applies.' })).toBe('This applies.');
    expect(ownText({ title: 'Scope', text: 'Other\nThis applies.' })).toBe('Other\nThis applies.');
  });
});

describe('document fallback', () => {
  it('splits by markdown headings', () => {
    const s = documentSections('Intro\n## One\nalpha\n### Two\nbeta');
    expect(s.map((x) => x.label)).toEqual(['Full text', 'One', 'Two']);
    expect(s[2].group).toBe('One');
  });

  it('splits PDF text by numbered headings, ignoring TOC lines', () => {
    const text = [
      '<!-- page 1 -->',
      '1. Background ........ 1',
      '1. Background and objectives',
      '.................................. 1',
      '1. Background and objectives',
      'text a',
      '2. Overview of practices',
      'text b',
      '2.1. Prohibitions listed in Article 5',
      'text c',
    ].join('\n');
    expect(documentSections(text).map((x) => x.label)).toEqual([
      'Full text',
      '1 Background and objectives',
      '2 Overview of practices',
      '2.1 Prohibitions listed in Article 5',
    ]);
  });

  it('matches and highlights search words', () => {
    const [s] = documentSections('plain text about bias');
    expect(sectionMatches(s, 'BIAS')).toBe(true);
    expect(sectionMatches(s, 'proxy')).toBe(false);
    expect(highlightParts('Bias and bias', 'bias').filter((p) => p.hit)).toHaveLength(2);
  });
});
