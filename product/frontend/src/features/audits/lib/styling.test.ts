import { describe, expect, it } from 'vitest';
import {
  canApproveDataset,
  ciCrosses,
  confidenceLabel,
  formatCI,
  gateCounts,
  gateTone,
  memoryIds,
  overallGateStatus,
  provenanceOfLine,
  verdictStyle,
  verdictToTraffic,
} from './styling';
import type { GateName, GateResult } from './types';

const pass: GateResult = { status: 'pass' };
const all = (s: GateResult): Record<GateName, GateResult> => ({
  schema: s,
  business_rules: s,
  realism: s,
  coverage: s,
  privacy: s,
});

describe('verdict styling', () => {
  it('maps the four verdicts to tones', () => {
    expect(verdictStyle('supports_compliance').tone).toBe('success');
    expect(verdictStyle('indicates_gap').tone).toBe('danger');
    expect(verdictStyle('inconclusive').tone).toBe('warning');
    expect(verdictStyle('not_assessable_by_testing').tone).toBe('neutral');
  });

  it('falls back to neutral for unknown verdicts', () => {
    expect(verdictStyle('weird')).toMatchObject({ label: 'weird', tone: 'neutral' });
  });

  it('maps verdicts to management traffic lights', () => {
    expect(verdictToTraffic('indicates_gap')).toBe('red');
    expect(verdictToTraffic('inconclusive')).toBe('amber');
    expect(verdictToTraffic('supports_compliance')).toBe('green');
    expect(verdictToTraffic('not_assessable_by_testing')).toBe('grey');
  });

  it('labels confidence and formats CIs', () => {
    expect(confidenceLabel(0.84)).toBe('high');
    expect(confidenceLabel(0.6)).toBe('medium');
    expect(confidenceLabel(0.3)).toBe('low');
    expect(formatCI([0.64, 0.78])).toBe('95% CI [0.64, 0.78]');
    expect(ciCrosses([-0.01, 0.13], 0.05)).toBe(true);
    expect(ciCrosses([0.64, 0.78], 0.8)).toBe(false);
  });
});

describe('gate status', () => {
  it('passes when all five gates pass', () => {
    expect(overallGateStatus(all(pass))).toBe('pass');
    expect(canApproveDataset(all(pass))).toBe(true);
  });

  it('warns on any warning and blocks on any fail', () => {
    expect(overallGateStatus({ ...all(pass), realism: { status: 'warn' } })).toBe('warn');
    expect(canApproveDataset({ ...all(pass), realism: { status: 'warn' } })).toBe(true);
    expect(overallGateStatus({ ...all(pass), privacy: { status: 'fail' } })).toBe('fail');
    expect(canApproveDataset({ ...all(pass), privacy: { status: 'fail' } })).toBe(false);
  });

  it('treats a missing gate as failed', () => {
    const { privacy: _p, ...four } = all(pass);
    expect(overallGateStatus(four)).toBe('fail');
    expect(gateCounts(four)).toEqual({ pass: 4, warn: 0, fail: 1 });
  });

  it('maps gate statuses to tones', () => {
    expect(gateTone('pass')).toBe('success');
    expect(gateTone('warn')).toBe('warning');
    expect(gateTone('fail')).toBe('danger');
  });
});

describe('provenance and memory ids', () => {
  it('reads provenance tags from YAML lines', () => {
    expect(provenanceOfLine('    provenance: llm_assumption        # x')).toBe('llm_assumption');
    expect(provenanceOfLine('    provenance: dictionary')).toBe('dictionary');
    expect(provenanceOfLine('    dist: {a: 1}')).toBeNull();
    expect(provenanceOfLine('    provenance: bogus')).toBeNull();
  });

  it('extracts unique memory ids', () => {
    expect(memoryIds('applied MEM-0042 and MEM-0057, again MEM-0042')).toEqual(['MEM-0042', 'MEM-0057']);
  });
});
