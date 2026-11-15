/**
 * A background task's whole conversation, folded from its own event stream (`WS /v1/tasks/{id}/ws`):
 * the instruction it was started with, then every turn in order. A follow-up the parent sent
 * (`update_async_task`, a TASK_INPUT event) is a `task_input` block that opens the next turn; the
 * sub-agent's thinking, tool steps and reply follow it, exactly as the chat folds an answer.
 *
 * Each run of a task streams through a fresh normalizer, so its `seq` restarts at 1: the stream
 * order is the truth, and `seq` is dropped before folding (the fold would skip a later run's
 * events as already seen).
 */
import { foldTimeline, type RunTimeline } from './timeline';
import type { RawEvent } from './types';

const SETTLED_TO_TERMINAL: Record<string, string> = {
  success: 'completed',
  completed: 'completed',
  error: 'failed',
  failed: 'failed',
  cancelled: 'cancelled',
};

export function foldTaskEvents(events: readonly RawEvent[], status: string | null | undefined): RunTimeline {
  const unsequenced = events.map((event) => {
    const copy: RawEvent = { ...event };
    delete copy.seq;
    return copy;
  });
  return foldTimeline(unsequenced, { status: status ? (SETTLED_TO_TERMINAL[status] ?? null) : null });
}

/** One turn of the transcript: who asked what, then the blocks that answered it. */
export interface TranscriptTurn {
  id: string;
  /** The instruction (the task's description for the first turn, else the follow-up). */
  instruction: string;
  /** False for the task's original instruction. */
  followUp: boolean;
  blocks: RunTimeline['blocks'];
}

/** The folded timeline split at each follow-up into turns. */
export function transcriptTurns(timeline: RunTimeline, firstInstruction: string): TranscriptTurn[] {
  const turns: TranscriptTurn[] = [
    { id: 'turn-0', instruction: firstInstruction, followUp: false, blocks: [] },
  ];
  for (const block of timeline.blocks) {
    if (block.kind === 'task_input') {
      turns.push({ id: block.id, instruction: block.text, followUp: true, blocks: [] });
      continue;
    }
    turns[turns.length - 1].blocks.push(block);
  }
  return turns;
}
