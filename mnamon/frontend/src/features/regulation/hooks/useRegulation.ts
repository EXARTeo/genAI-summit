import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { regulationApi } from '../handlers/regulation';
import type { DemoMirrorEdit, JudgeDecision } from '../lib/types';

export const regKeys = {
  sources: ['regulation', 'sources'] as const,
  text: (docId: string, version?: number) => ['regulation', 'text', docId, version ?? 'latest'] as const,
  diff: (docId: string, from: number, to: number) => ['regulation', 'diff', docId, from, to] as const,
  changes: ['regulation', 'changes'] as const,
};

export function useRegSources() {
  return useQuery({ queryKey: regKeys.sources, queryFn: regulationApi.sources });
}

export function useDocText(docId: string | undefined, version?: number) {
  return useQuery({
    queryKey: regKeys.text(docId ?? '', version),
    queryFn: () => regulationApi.text(docId!, version),
    enabled: !!docId,
  });
}

export function useDocDiff(docId: string | undefined, from: number, to: number) {
  return useQuery({
    queryKey: regKeys.diff(docId ?? '', from, to),
    queryFn: () => regulationApi.diff(docId!, from, to),
    enabled: !!docId && to > from,
  });
}

/** The change inbox; polls while a change judge is running. */
export function useRegChanges() {
  return useQuery({
    queryKey: regKeys.changes,
    queryFn: regulationApi.changes,
    refetchInterval: (q) => (q.state.data?.some((c) => c.judge === 'running') ? 3000 : false),
  });
}

/** "Simulate change" (demo): edit the mirror, check it, then refresh the inbox. */
export function useSimulateChange() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: DemoMirrorEdit) => regulationApi.simulateChange({ ...body, check: true }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: regKeys.changes });
      void qc.invalidateQueries({ queryKey: regKeys.sources });
    },
  });
}

export function useDecideChange() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; status: 'accepted' | 'rejected' }) =>
      regulationApi.decideChange(v.id, { status: v.status }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: regKeys.changes }),
  });
}

export function useOverrideJudge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; systemId: string; decision: JudgeDecision }) =>
      regulationApi.overrideJudge(v.id, v.systemId, v.decision),
    onSuccess: () => void qc.invalidateQueries({ queryKey: regKeys.changes }),
  });
}

/** "Check now": queue a reg-memory watch check, then refresh sources and changes as it lands. */
export function useCheckNow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: regulationApi.checkNow,
    onSuccess: () => {
      const refresh = () => {
        void qc.invalidateQueries({ queryKey: regKeys.sources });
        void qc.invalidateQueries({ queryKey: regKeys.changes });
      };
      refresh();
      for (const ms of [5_000, 15_000, 45_000]) setTimeout(refresh, ms);
    },
  });
}
