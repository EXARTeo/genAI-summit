/**
 * One background task of the open conversation, read from the task list the agent map already
 * loads (never fetched here). A follow-up's launch event names no sub-agent (`update_async_task`
 * takes only the task id), so its marker takes the name from here.
 */
import { useQuery } from '@tanstack/react-query';
import { useChatUi } from '../components/chatContext';
import type { TaskOut } from '../lib/types';
import { chatKeys } from './keys';

export function useTaskRecord(taskId: string): TaskOut | null {
  const { conversationId } = useChatUi();
  const tasks = useQuery<TaskOut[]>({
    queryKey: chatKeys.tasks(conversationId ?? ''),
    queryFn: () => Promise.resolve([]),
    enabled: false,
  });
  return tasks.data?.find((task) => task.task_id === taskId) ?? null;
}
