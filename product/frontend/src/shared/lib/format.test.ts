import { describe, expect, it } from 'vitest';
import { formatRelative } from './format';

const now = new Date('2026-11-14T18:00:00Z');

describe('formatRelative', () => {
  it('formats the past', () => {
    expect(formatRelative('2026-11-14T16:00:00Z', now)).toBe('2 hours ago');
    expect(formatRelative('2026-11-14T17:59:30Z', now)).toBe('just now');
  });

  it('treats a near-future timestamp as clock skew', () => {
    expect(formatRelative('2026-11-14T18:40:00Z', now)).toBe('just now');
  });

  it('is empty for missing dates', () => {
    expect(formatRelative(null, now)).toBe('');
  });
});
