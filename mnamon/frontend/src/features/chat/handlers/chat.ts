/** Chat API calls (port of magenticx `shared/lib/api/{conversations,inference,search,attachments}.ts`). */
import { api } from '@/shared/lib/api';
import { chatApi } from '../lib/routes';
import type {
  AgentManifest,
  ConversationDetail,
  ConversationSummary,
  InferenceRunOut,
  InferenceStartPayload,
  InferenceStartResponse,
  Page,
  QueuedStartResponse,
  ResumePayload,
  SearchResult,
  TaskOut,
} from '../lib/types';

export const listConversations = (size = 100) =>
  api.get<Page<ConversationSummary>>(chatApi.conversations, { query: { page: 1, size } });
/** One page of the sidebar's Chats list (pinned and archived chats are not in it). */
export const listConversationsPage = (page: number, size: number) =>
  api.get<Page<ConversationSummary>>(chatApi.conversations, { query: { page, size } });
export const listPinned = () =>
  api.get<Page<ConversationSummary>>(chatApi.pinned, { query: { page: 1, size: 50 } });
export const listArchived = () =>
  api.get<Page<ConversationSummary>>(chatApi.archived, { query: { page: 1, size: 100 } });
export const getConversation = (id: string) => api.get<ConversationDetail>(chatApi.conversation(id));
export const deleteConversation = (id: string) => api.delete<void>(chatApi.conversation(id));
export const renameConversation = (id: string, title: string) =>
  api.patch<ConversationSummary>(chatApi.title(id), { title });
export const setPinned = (id: string, pinned: boolean) =>
  api.patch<ConversationSummary>(pinned ? chatApi.pin(id) : chatApi.unpin(id));
export const setArchived = (id: string, archived: boolean) =>
  api.patch<ConversationSummary>(archived ? chatApi.archive(id) : chatApi.unarchive(id));
export const forkConversation = (id: string, messageId: string) =>
  api.post<{ detail: ConversationDetail; summary: ConversationSummary }>(chatApi.fork(id), { messageId });

export const rateMessage = (conversationId: string, messageId: string, liked: boolean) =>
  api.post<unknown>(
    liked ? chatApi.like(conversationId, messageId) : chatApi.dislike(conversationId, messageId),
  );

export const startRun = (payload: InferenceStartPayload) =>
  api.post<InferenceStartResponse | QueuedStartResponse>(chatApi.start, payload);
export const listActiveRuns = () => api.get<InferenceRunOut[]>(chatApi.runs, { query: { status: 'active' } });
/** All of the caller's runs (the socket fallback reads a run's status from here). */
export const listRuns = () => api.get<InferenceRunOut[]>(chatApi.runs);
export const cancelRun = (runId: string) => api.post<InferenceRunOut>(chatApi.cancel(runId));
export const resumeRun = (runId: string, payload: ResumePayload) =>
  api.post<InferenceRunOut>(chatApi.resume(runId), payload);
export const cancelQueued = (conversationId: string) => api.delete<void>(chatApi.queued(conversationId));

export const listTasks = (conversationId: string) => api.get<TaskOut[]>(chatApi.tasks(conversationId));
export const cancelTask = (taskId: string) => api.post<TaskOut>(chatApi.cancelTask(taskId));

export const searchChats = (q: string, signal?: AbortSignal) =>
  api.get<SearchResult[]>(chatApi.search, { query: { q, limit: 20 }, signal });

/** The agent catalog; falls back to the default agent while the backend does not proxy it. */
/** The agents catalog; the chat filters it to chat-capable agents (`lib/agents.ts`). */
export async function listAgents(): Promise<AgentManifest[]> {
  const agents = await api.get<AgentManifest[]>(chatApi.agents);
  return Array.isArray(agents) ? agents : [];
}

export const downloadAttachmentBlob = (conv: string, msg: string, blob: string) =>
  api.get<Blob>(chatApi.download(conv, msg, blob), { responseType: 'blob' });
export const previewAttachmentBlob = (conv: string, msg: string, blob: string) =>
  api.get<Blob>(chatApi.preview(conv, msg, blob), { responseType: 'blob' });

export const saveAttachmentToSystem = (systemId: string, attachmentId: string, path?: string) =>
  api.post<{ file: { path: string; version: number }; changed: boolean }>(chatApi.saveToSystem(systemId), {
    attachmentId,
    path: path ?? null,
    reason: 'Saved from chat',
  });
