import { useMemo } from 'react';
import { useAudits } from '@/features/audits/hooks/useAudits';
import { openGates } from '../lib/approvals';

/** All open HITL gates across audits (list endpoint has no approvals, so stage + status decide). */
export function useOpenGates() {
  const q = useAudits();
  const gates = useMemo(
    () => openGates((q.data ?? []).map((a) => ({ ...a, artifacts: [], approvals: [] }))),
    [q.data],
  );
  return { ...q, gates };
}
