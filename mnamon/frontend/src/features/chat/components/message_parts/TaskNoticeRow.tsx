/**
 * A wake-up's input row (`messages.kind = task_notification`; port of magenticx
 * `TaskNoticeRow.tsx`): the system telling the orchestrator a background task settled. A
 * `user`-sender row in the tree (the graph input is a HumanMessage) but never the user's words,
 * so it is drawn as one compact marker, "General Purpose finished · 22s", not a bubble, with no
 * edit, copy or branch controls. A click opens that task in the agent map.
 */
import { useAgentMapNav } from '../../hooks/useAgentMapNav';
import { taskNoticeText } from '../../lib/taskMarkers';
import type { MessageOut } from '../../lib/types';
import { TaskMarker } from './ConversationMarkers';

export function TaskNoticeRow({ message }: { message: MessageOut }) {
  const openTask = useAgentMapNav((s) => s.openTask);
  const notice = message.taskNotice;
  if (!notice) return <TaskMarker status="success" text="A background task finished" />;
  return (
    <TaskMarker
      status={notice.status}
      text={taskNoticeText(notice)}
      onOpen={() => openTask(notice.task_id)}
    />
  );
}
