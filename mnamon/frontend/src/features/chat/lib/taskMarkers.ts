/**
 * The words of the conversation's background-task markers (magenticx `taskTreeAdapter`
 * `taskOutcomeVerb` / `taskSettledText` / `taskNoticeText`): "General Purpose finished · 22s",
 * "Sent an update to General Purpose".
 */
import { formatAgentDuration } from './agentMap';
import { toTitleCase } from './hitl';
import type { TaskNotice } from './types';

export type TaskOutcome = 'success' | 'error' | 'cancelled' | 'running';

/** A task status from any source (notice row, inline settle, task list) as a marker outcome. */
export function taskOutcome(status: string | null | undefined): TaskOutcome {
  if (status === 'success' || status === 'completed' || status === 'done') return 'success';
  if (status === 'error' || status === 'failed') return 'error';
  if (status === 'cancelled') return 'cancelled';
  return 'running';
}

/** How a task's end reads in a sentence ("researcher finished"). */
export function taskOutcomeVerb(status: string | null | undefined): string {
  const outcome = taskOutcome(status);
  if (outcome === 'error') return 'failed';
  if (outcome === 'cancelled') return 'was stopped';
  if (outcome === 'success') return 'finished';
  return 'is still working';
}

/** The sub-agent's name as its cards show it. */
export const taskTitle = (name: string | null | undefined): string =>
  toTitleCase(name ?? undefined) ?? name ?? 'Background task';

/** "General Purpose finished". */
export function taskSettledText(name: string, status: string | null | undefined): string {
  return `${taskTitle(name)} ${taskOutcomeVerb(status)}`;
}

/** The notice row's line: "General Purpose finished · 2m 14s". */
export function taskNoticeText(notice: TaskNotice): string {
  const head = taskSettledText(notice.name, notice.status);
  const duration = formatAgentDuration(notice.duration_ms ?? null);
  return duration ? `${head} · ${duration}` : head;
}

/** "Sent an update to General Purpose": the orchestrator followed up on a running or settled task. */
export function taskUpdateText(name: string): string {
  return `Sent an update to ${taskTitle(name)}`;
}
