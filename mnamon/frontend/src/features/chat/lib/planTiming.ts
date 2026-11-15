/**
 * When each step of the agent's plan started and finished (port of magenticx
 * `features/inference/planTiming.ts`). The agent rewrites its whole checklist (`write_todos`) on
 * every change, and each PLAN_SNAPSHOT carries the agents service's clock (`updated_at`);
 * successive snapshots tell when a step changed state:
 *
 *   first seen in progress            → started at that snapshot
 *   first seen done (after started)   → finished at that snapshot
 *   done without ever being seen in progress, or a snapshot with no time
 *                                     → that moment is unknown (null)
 *
 * The persisted event log keeps every snapshot, so the same walk gives the same times live (the
 * run timeline's fold) and after a reload. Only real transitions are stamped; nothing is guessed.
 */

export interface PlanStepItem {
  content: string;
  status: string;
}

export interface PlanStepTiming {
  /** null: it started, but when is unknown. */
  startedAt?: number | null;
  endedAt?: number | null;
}

const normalize = (content: string) => content.replace(/\s+/g, ' ').trim().toLowerCase();

/** A step's identity across rewrites: its text, numbered when the same text appears twice. */
export function planStepKeys(items: PlanStepItem[]): string[] {
  const seen = new Map<string, number>();
  return items.map((item) => {
    const text = normalize(item.content);
    const count = seen.get(text) ?? 0;
    seen.set(text, count + 1);
    return count ? `${text}#${count}` : text;
  });
}

/** The time a snapshot stands for: its own stamp, else the event's. */
export function planSnapshotTime(
  value: { updated_at?: unknown },
  event?: { timestamp?: unknown },
): number | undefined {
  if (typeof value.updated_at === 'number' && Number.isFinite(value.updated_at)) return value.updated_at;
  const stamp = event?.timestamp;
  return typeof stamp === 'number' && Number.isFinite(stamp) ? stamp : undefined;
}

/**
 * The timings after `next` replaces `previous`. A step is matched by its text; one reworded in
 * place (its old text gone from the new list) keeps the timing of the step it replaces.
 */
export function advancePlanTimings(
  previous: PlanStepItem[] | null,
  timings: PlanStepTiming[] | undefined,
  next: PlanStepItem[],
  at: number | undefined,
): PlanStepTiming[] {
  const previousKeys = previous ? planStepKeys(previous) : [];
  const nextKeys = planStepKeys(next);
  const previousIndex = new Map(previousKeys.map((key, index) => [key, index]));
  const nextSet = new Set(nextKeys);
  const stamp = at ?? null;

  return next.map((item, index) => {
    let from = previousIndex.get(nextKeys[index]);
    if (from === undefined && previous && index < previous.length && !nextSet.has(previousKeys[index])) {
      from = index;
    }
    const before = from !== undefined && previous ? previous[from].status : null;
    const timing: PlanStepTiming = { ...(from !== undefined ? timings?.[from] : undefined) };

    if (item.status === 'in_progress') {
      if (timing.startedAt === undefined) timing.startedAt = stamp;
      // Reopened: it has not finished after all.
      timing.endedAt = undefined;
    } else if (item.status === 'completed') {
      // Done without being seen at work: when it started is unknown.
      if (timing.startedAt === undefined) timing.startedAt = null;
      // Already done in the answer's first snapshot: it finished before then.
      if (before !== 'completed') timing.endedAt = previous ? stamp : null;
    } else {
      timing.endedAt = undefined;
    }
    return timing;
  });
}

/** How long a step took, when both ends are known (and in order). */
export function planStepDurationMs(timing: PlanStepTiming | undefined): number | null {
  const startedAt = timing?.startedAt;
  const endedAt = timing?.endedAt;
  if (typeof startedAt !== 'number' || typeof endedAt !== 'number') return null;
  return endedAt >= startedAt ? endedAt - startedAt : null;
}
