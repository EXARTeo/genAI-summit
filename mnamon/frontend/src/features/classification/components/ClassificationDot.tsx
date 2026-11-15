import { cn } from '@/shared/lib/utils';
import { Tooltip } from '@/shared/ui';
import { useClassifications } from '../hooks/useClassifications';
import { attention } from '../lib/classification';

const COPY = {
  proposed: 'A proposed classification is waiting for approval',
  stale: 'Stale: a regulation change touched the approved classification',
};

/** A small dot next to the header's risk badge: a proposal waits (info) or the class is stale (warning). */
export function ClassificationDot({ systemId }: { systemId: string }) {
  const { data } = useClassifications(systemId);
  const state = data ? attention(data) : null;
  if (!state) return null;
  return (
    <Tooltip content={COPY[state]}>
      <span
        role="img"
        tabIndex={0}
        aria-label={COPY[state]}
        className="inline-flex items-center gap-1 rounded-full text-2xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className={cn('size-2 rounded-full', state === 'stale' ? 'bg-warning' : 'bg-info')} />
        <span className={state === 'stale' ? 'text-warning' : 'text-info'}>{state}</span>
      </span>
    </Tooltip>
  );
}
