import { cn } from '@/shared/lib/utils';

export type RunChip = 'live' | 'waiting' | 'done' | 'failed' | 'replay' | 'idle';

const CHIP: Record<RunChip, { label: string; cls: string; dot: string; pulse?: boolean }> = {
  live: { label: 'Live', cls: 'bg-primary/12 text-primary', dot: 'bg-primary', pulse: true },
  waiting: { label: 'Waiting for you', cls: 'bg-warning/15 text-warning', dot: 'bg-warning', pulse: true },
  done: { label: 'Finished', cls: 'bg-success/12 text-success', dot: 'bg-success' },
  failed: { label: 'Failed', cls: 'bg-danger/12 text-danger', dot: 'bg-danger' },
  replay: { label: 'Replay', cls: 'bg-primary/12 text-primary', dot: 'bg-primary', pulse: true },
  idle: { label: 'Not started', cls: 'bg-surface-sunken text-muted', dot: 'bg-muted' },
};

/** The pipeline card's header: title, run chip, step count, progress, follow-live control. */
export function PipelineHeader({
  chip,
  stepText,
  progress,
  follow,
  onFollow,
}: {
  chip: RunChip;
  stepText: string;
  /** 0..1 */
  progress: number;
  follow: boolean;
  onFollow: () => void;
}) {
  const c = CHIP[chip];
  return (
    <div className="px-5 pb-4 pt-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 className="text-[15px] font-semibold tracking-tight">Pipeline</h2>
        <span
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium',
            c.cls,
          )}
        >
          <span className="relative flex size-1.5">
            {c.pulse && (
              <span
                className={cn('absolute inset-0 rounded-full opacity-60 motion-safe:animate-ping', c.dot)}
              />
            )}
            <span className={cn('relative size-1.5 rounded-full', c.dot)} />
          </span>
          {c.label}
        </span>
        <span className="num ml-auto text-[13px] text-muted">{stepText}</span>
      </div>
      <div className="mt-3 h-1 overflow-hidden rounded-full bg-surface-sunken">
        <div
          className={cn(
            'h-full rounded-full transition-[width] duration-500 ease-out',
            chip === 'waiting' ? 'bg-warning' : chip === 'failed' ? 'bg-danger' : 'bg-primary',
          )}
          style={{ width: `${Math.round(progress * 100)}%` }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-muted">
        <span>{follow ? 'Following the live step' : 'Showing the step you picked'}</span>
        {!follow && (
          <button type="button" className="font-medium text-primary hover:underline" onClick={onFollow}>
            Follow live
          </button>
        )}
      </div>
    </div>
  );
}
