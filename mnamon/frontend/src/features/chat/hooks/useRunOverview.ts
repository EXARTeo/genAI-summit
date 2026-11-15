import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { listTasks } from '../handlers/chat';
import { buildAgentMap, collectAgentMapAnswers, type AgentMap, type AnswerTimeline } from '../lib/agentMap';
import { buildConversationPlans, collectPlanAnswers, type ConversationPlans } from '../lib/conversationPlans';
import { isActiveRun } from '../lib/runState';
import { chatKeys } from './keys';
import type { ChatController } from './useChat';

const SETTLED_TASKS = new Set(['success', 'error', 'cancelled']);
const TASK_POLL_MS = 3000;

/**
 * The agent map and the plans of the branch the user sees (magenticx `useAgentMap` +
 * `useConversationPlans`). Each answer's timeline comes from the chat's own `runView`: the live
 * run's fold while it streams, the stored event log once settled (cached per message), so a
 * streamed frame rebuilds only the answer it belongs to. Background tasks (every Mnamon sub-agent
 * runs as one) come from the conversation's task list, polled while a run or a task is working.
 */
export function useRunOverview(chat: Pick<ChatController, 'path' | 'runView' | 'activeRun' | 'detail'>): {
  map: AgentMap;
  plans: ConversationPlans;
} {
  const { path, runView, activeRun } = chat;
  const conversationId = chat.detail?.id ?? null;
  const working = Boolean(activeRun) || Boolean(chat.detail?.hasActiveTasks);
  const tasks = useQuery({
    queryKey: chatKeys.tasks(conversationId ?? ''),
    queryFn: () => listTasks(conversationId as string),
    enabled: Boolean(conversationId),
    refetchInterval: (query) =>
      working || (query.state.data ?? []).some((task) => !SETTLED_TASKS.has(task.status))
        ? TASK_POLL_MS
        : false,
  });
  const taskList = tasks.data;

  return useMemo(() => {
    const byId = new Map(path.map((message) => [message.id, message]));
    const read: AnswerTimeline = (branch) => {
      const message = byId.get(branch.id);
      const run = message ? runView(message) : null;
      return { timeline: run?.timeline ?? null, live: isActiveRun(run) };
    };
    return {
      map: buildAgentMap(collectAgentMapAnswers(path, read), taskList ?? []),
      plans: buildConversationPlans(collectPlanAnswers(path, read)),
    };
  }, [path, runView, taskList]);
}
