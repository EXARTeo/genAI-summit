import { useCallback, useEffect, useMemo, useState } from 'react';
import { STAGES } from '../lib/pipeline';
import type { AuditDetail } from '../lib/types';

const STEP_MS = 1100;
const GATE_MS = 1900;

/** Pure: the audit as it looked when the run had reached stage `idx`. */
export function auditAtStage(audit: AuditDetail, idx: number): AuditDetail {
  if (idx >= STAGES.length) return audit;
  const stage = STAGES[idx];
  const visible = new Set(STAGES.slice(0, idx).flatMap((s) => s.kinds as string[]));
  return {
    ...audit,
    stage: stage.id,
    status: stage.gate ? 'waiting_approval' : 'running',
    artifacts: audit.artifacts.filter((a) => visible.has(a.kind)),
  };
}

/**
 * Client-side replay of a finished audit: walks the Stepper through every stage
 * (pausing on the gates) using the stored artifacts. Demo aid; works in mock and real mode.
 */
export function useReplay(audit: AuditDetail | undefined) {
  const [idx, setIdx] = useState<number | null>(null);

  useEffect(() => {
    if (idx == null) return;
    if (idx >= STAGES.length) {
      setIdx(null);
      return;
    }
    const t = setTimeout(
      () => setIdx((i) => (i == null ? null : i + 1)),
      STAGES[idx].gate ? GATE_MS : STEP_MS,
    );
    return () => clearTimeout(t);
  }, [idx]);

  const start = useCallback(() => setIdx(0), []);
  const stop = useCallback(() => setIdx(null), []);
  const view = useMemo(() => (audit && idx != null ? auditAtStage(audit, idx) : audit), [audit, idx]);
  return { view, replaying: idx != null, start, stop, index: idx };
}
