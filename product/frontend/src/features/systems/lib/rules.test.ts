import { describe, expect, it } from 'vitest';
import { handleMockRequest } from '@/shared/lib/mocks/router';
import { parseBusinessRules, ruleProposalYaml, slugify } from './rules';

describe('business rules', () => {
  it('parses bullets under headings with a kind per heading', () => {
    const md = [
      '# Title',
      '## What valid applicant data looks like',
      '- Applicants are 18 to 67 years old.',
      '- Nobody starts working before 16:',
      '  years of experience can be at most (age - 16).',
      '## Policies',
      '- Sex must not be used.',
    ].join('\n');
    const rules = parseBusinessRules(md, 'cv-ranker');
    expect(rules).toHaveLength(3);
    expect(rules[0].kind).toBe('hard');
    expect(rules[1].text).toContain('at most (age - 16)');
    expect(rules[2].kind).toBe('policy');
  });

  it('builds a proposal and a safe slug', () => {
    expect(slugify('Ages: 18 to 67!')).toBe('ages-18-to-67');
    const y = ruleProposalYaml({
      systemId: 'SYS-001',
      plugin: 'cv-ranker',
      kind: 'hard',
      text: 'a "b"',
      rationale: 'r',
    });
    expect(y).toContain('status: proposed');
    expect(y).toContain('rule: "a \\"b\\""');
  });
});

describe('mock mode', () => {
  it('serves the four seeded systems without answer keys', async () => {
    const res = await handleMockRequest('/api/v1/systems', { method: 'GET' });
    const systems = (await res.json()) as { id: string }[];
    expect(systems.map((s) => s.id)).toEqual(['SYS-001', 'SYS-002', 'SYS-003', 'SYS-004']);
    const tree = await (await handleMockRequest('/api/v1/systems/SYS-001/files', { method: 'GET' })).json();
    expect(tree.some((f: { path: string }) => f.path.includes('_answer-key'))).toBe(false);
  });

  it('reads a file as JSON and lists versions', async () => {
    const f = await (
      await handleMockRequest('/api/v1/systems/SYS-001/files/system-card.yaml?format=json', { method: 'GET' })
    ).json();
    expect(f.text).toContain('CV Screener');
    const v = await (
      await handleMockRequest(
        '/api/v1/systems/SYS-001/files/plugins/cv-ranker/docs/known-issues.md/versions',
        {
          method: 'GET',
        },
      )
    ).json();
    expect(v.length).toBe(2);
  });
});
