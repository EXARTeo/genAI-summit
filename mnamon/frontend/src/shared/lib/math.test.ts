import { describe, expect, it } from 'vitest';
import { plainMath } from './math';

describe('plainMath', () => {
  it('turns LaTeX comparison spans into symbols', () => {
    expect(plainMath('threshold $\\le 0.05$ and $\\ge 0.8$')).toBe('threshold ≤ 0.05 and ≥ 0.8');
    expect(plainMath('CI $\\pm 0.02$, $10\\%$')).toBe('CI ± 0.02, 10%');
  });

  it('leaves prices and plain dollar text alone', () => {
    expect(plainMath('loans of $500 to $1000')).toBe('loans of $500 to $1000');
    expect(plainMath('costs $5 and $7 total')).toBe('costs $5 and $7 total');
  });
});
