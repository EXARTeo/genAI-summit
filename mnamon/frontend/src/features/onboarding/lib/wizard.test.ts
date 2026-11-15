import { parse } from 'yaml';
import { describe, expect, it } from 'vitest';
import {
  EMPTY_FORM,
  buildCard,
  cardYaml,
  docPath,
  exampleForm,
  firstInvalidStep,
  isReadable,
  mergeFiles,
  nextSystemId,
  stepErrors,
} from './wizard';

describe('nextSystemId', () => {
  it('proposes the next free SYS number', () => {
    expect(nextSystemId(['SYS-001', 'SYS-003', 'other'])).toBe('SYS-004');
    expect(nextSystemId([])).toBe('SYS-001');
  });
});

describe('stepErrors', () => {
  it('validates the id pattern, uniqueness and the acquisition', () => {
    const f = { ...EMPTY_FORM, id: '-bad id', name: 'X' };
    expect(stepErrors('identity', f).id).toMatch(/Letters, digits/);
    expect(stepErrors('identity', { ...f, id: 'sys-001' }, ['SYS-001']).id).toMatch(/already registered/);
    expect(stepErrors('identity', { ...f, id: 'SYS-009' }).acquisition).toBeTruthy();
    expect(stepErrors('identity', { ...f, id: 'SYS-009', acquisition: 'in_house' })).toEqual({});
  });

  it('requires the purpose and the profiling answer', () => {
    const e = stepErrors('purpose', EMPTY_FORM);
    expect(Object.keys(e).sort()).toEqual(['description', 'intended_purpose', 'profiling']);
  });

  it('asks for the product law only when the safety switch is on', () => {
    const f = { ...EMPTY_FORM, affected_persons: 'Applicants' };
    expect(stepErrors('deployment', f)).toEqual({});
    expect(stepErrors('deployment', { ...f, safety_component: true }).annex_i_product).toBeTruthy();
  });

  it('the example passes every step', () => {
    expect(firstInvalidStep(exampleForm('SYS-004'), ['SYS-001'])).toBe(-1);
    expect(firstInvalidStep(EMPTY_FORM)).toBe(0);
  });
});

describe('buildCard', () => {
  it('writes an unclassified card declared by the PM', () => {
    const card = buildCard({ ...exampleForm('SYS-004'), features: ['interacts_with_persons'] });
    expect(card).toMatchObject({
      id: 'SYS-004',
      name: 'CV Parser',
      risk_class: 'unclassified',
      acquisition: 'in_house',
      profiling: 'no',
      features: ['interacts_with_persons'],
      annex_i_product: null,
      provenance: 'declared_by_pm',
      deployment: { status: 'pilot', countries: ['GR', 'CY'] },
    });
    expect(parse(cardYaml(card))).toEqual(card);
  });

  it('keeps the product law only with the safety switch', () => {
    const f = { ...exampleForm('S'), annex_i_product: 'Machinery' };
    expect(buildCard(f).annex_i_product).toBeNull();
    expect(buildCard({ ...f, safety_component: true }).annex_i_product).toBe('Machinery');
  });
});

describe('documents', () => {
  it('maps names to docs/ paths and tells readable files apart', () => {
    expect(docPath('My Spec.md')).toBe('docs/My-Spec.md');
    expect(docPath('../x/y.txt')).toBe('docs/x-y.txt');
    expect(isReadable('a.YAML')).toBe(true);
    expect(isReadable('a.pdf')).toBe(false);
  });

  it('replaces a file picked twice', () => {
    const a = new File(['1'], 'a.md');
    const a2 = new File(['22'], 'a.md');
    const b = new File(['3'], 'b.md');
    expect(mergeFiles([a, b], [a2]).map((f) => f.size)).toEqual([2, 1]);
  });
});
