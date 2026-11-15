import { describe, expect, it } from 'vitest';
import { latexToText, plainMath } from './mathText';

describe('plainMath', () => {
  it('turns inline LaTeX into plain text', () => {
    expect(plainMath('flip rate $\\le 0.02$ (org limit)')).toBe('flip rate ≤ 0.02 (org limit)');
    expect(plainMath('ratio \\(\\ge 0.80\\)')).toBe('ratio ≥ 0.80');
    expect(plainMath('$10\\%$ of decisions')).toBe('10% of decisions');
    expect(latexToText('\\frac{a}{b} \\times \\text{n}')).toBe('a/b × n');
  });

  it('leaves money, code spans and code fences alone', () => {
    expect(plainMath('costs $5 to $10 a month')).toBe('costs $5 to $10 a month');
    expect(plainMath('run `echo $\\le$` now')).toBe('run `echo $\\le$` now');
    const fence = '```\nx = "$\\le$"\n```\nthen $\\le 1$';
    expect(plainMath(fence)).toBe('```\nx = "$\\le$"\n```\nthen ≤ 1');
  });
});
