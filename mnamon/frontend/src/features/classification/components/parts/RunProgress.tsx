import { useEffect, useState } from 'react';
import { Stepper, type StepState } from '@/shared/ui';
import { formatElapsed, runPhase } from '../../lib/classification';

const STEPS = [
  { id: 'prechecks', title: 'Pre-checks', description: 'Annex III, Art. 5, Art. 50, role (code)' },
  { id: 'classifier', title: 'Classifier', description: 'Reads the dossier and the law (Gemini)' },
  { id: 'verify', title: 'Verify + Iris', description: 'Citations checked, independent judge' },
];

/** Three-step progress of a running classification with the elapsed time (estimated from the clock). */
export function RunProgress({ startedAt }: { startedAt: string }) {
  const start = Date.parse(startedAt) || Date.now();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const elapsed = now - start;
  const phase = runPhase(elapsed);
  const state = (i: number): StepState => (i < phase ? 'done' : i === phase ? 'active' : 'pending');

  return (
    <div className="space-y-4">
      <Stepper
        orientation="horizontal"
        steps={STEPS.map((s, i) => ({ id: s.id, title: s.title, state: state(i) }))}
      />
      <p className="text-center text-xs text-muted">
        <span aria-live="polite">{STEPS[phase].description}</span> ·{' '}
        <span className="num">{formatElapsed(elapsed)}</span> elapsed, usually under a minute
      </p>
    </div>
  );
}
