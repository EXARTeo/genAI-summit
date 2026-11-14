import { describe, expect, it } from 'vitest';
import { actorLabel, auditLabel, isHashLike } from './labels';

describe('labels', () => {
  it('keeps readable audit ids and replaces uuids', () => {
    expect(auditLabel({ id: 'SYS-002-20261115-0930', systemId: 'SYS-002' })).toBe('SYS-002-20261115-0930');
    const label = auditLabel({
      id: '36782b10-243b-4257-b62b-b592b8c68473',
      systemId: 'SYS-001',
      createdAt: '2026-11-14T21:22:18Z',
    });
    expect(label).toMatch(/^SYS-001 · 14 Nov 2026/);
    expect(isHashLike(label)).toBe(false);
  });

  it('labels actors without their uuid', () => {
    expect(actorLabel('client:ba110c49-f90e-439d-9b51-777458f97a87')).toBe('Engineer');
    expect(actorLabel('agent:audit-pipeline')).toBe('audit-pipeline agent');
    expect(actorLabel('engineer:you')).toBe('you');
  });

  it('detects hashes', () => {
    expect(isHashLike('ds-sha256:5877c86b67a695defcdc29b57aa99a500260126bc73ccbd6a0bda7c7fbe62cdf')).toBe(
      true,
    );
    expect(isHashLike('ce2d6dcd135c46558ef4552d53e82df2')).toBe(true);
    expect(isHashLike('SYS-001.cv-ranker')).toBe(false);
  });
});
