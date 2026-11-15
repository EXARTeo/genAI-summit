/**
 * "General Purpose finished" inside an answer (port of magenticx `TaskSettledMarker.tsx`): a
 * background task's result was pulled into this run while it was busy (TASK_SETTLED_INLINE),
 * instead of waking the orchestrator with a run of its own. Stored with the run's events, so the
 * moment the result arrived survives a reload. A click opens the task in the agent map.
 */
import { useAgentMapNav } from '../../hooks/useAgentMapNav';
import { taskSettledText } from '../../lib/taskMarkers';
import type { TaskSettledBlock } from '../../lib/timeline';
import { TaskMarker } from './ConversationMarkers';

export function TaskSettledMarker({ block }: { block: TaskSettledBlock }) {
  const openTask = useAgentMapNav((s) => s.openTask);
  return (
    <TaskMarker
      status={block.status}
      text={taskSettledText(block.name, block.status)}
      onOpen={() => openTask(block.taskId)}
    />
  );
}
