/**
 * Chat DTOs, mirroring the backend (`mnamon/backend/schema/{conversations,messages,attachments,
 * inference,search}.py`). Ported from magenticx's `shared/lib/types/*` and trimmed to what our
 * backend serves: no users, sharing, voice, effort or workflows.
 */

export type Sender = 'user' | 'ai';

export interface AttachmentOut {
  id: string;
  name: string;
  mime: string;
  size?: number | null;
  timestamp: string;
  /** `upload` (the user's file) or `generated` (a file the agent produced). */
  origin?: 'upload' | 'generated' | string;
  title?: string | null;
  summary?: string | null;
  blobId?: string | null;
  /** Base64 bytes, images only. */
  data?: string | null;
}

export interface AttachmentIn {
  name: string;
  mime: string;
  dataB64: string;
  size?: number;
}

export interface TaskNotice {
  task_id: string;
  name: string;
  status: string;
  duration_ms?: number | null;
}

export type RawEvent = Record<string, unknown> & { type?: string; seq?: number; timestamp?: number };

export interface MessageOut {
  id: string;
  parentMessageId: string | null;
  content: string | null;
  sender: Sender;
  liked?: boolean | null;
  agentSlug?: string | null;
  agentName?: string | null;
  created_at: string;
  updated_at: string;
  attachments: AttachmentOut[];
  thinking?: string[] | null;
  thinkingTime?: number | null;
  error?: boolean | null;
  errorMessage?: string | null;
  /** queued / running / cancelling while live, then completed / cancelled / failed. */
  streamingStatus?: string | null;
  rawEvents: RawEvent[];
  kind?: 'task_notification' | null;
  taskNotice?: TaskNotice | null;
}

export interface MessageIn {
  parentMessageId?: string | null;
  sender: Sender;
  content?: string | null;
  attachments?: AttachmentIn[];
}

export interface ConversationSummary {
  id: string;
  agentSlug: string;
  agentName?: string | null;
  forkedParentId?: string | null;
  forkedMessageId?: string | null;
  title?: string | null;
  isArchived: boolean;
  archivedAt?: string | null;
  isPinned: boolean;
  pinnedAt?: string | null;
  activeRunId?: string | null;
  hasActiveTasks?: boolean;
  lastMessage?: string | null;
  systemId?: string | null;
  auditId?: string | null;
  created_at: string;
  updated_at: string;
  isStreaming?: boolean;
}

export interface ConversationDetail extends ConversationSummary {
  activeTaskMessageId?: string | null;
  messages: MessageOut[];
}

export interface Page<T> {
  items: T[];
  total?: number;
  page?: number;
  size?: number;
  pages?: number;
}

export type InferenceMode = 'new' | 'send' | 'edit' | 'retry';

export interface InferenceStartPayload {
  mode: InferenceMode;
  agentSlug?: string;
  agentName?: string;
  title?: string;
  systemId?: string;
  auditId?: string;
  conversationId?: string;
  parentMessageId?: string | null;
  targetMessageId?: string;
  messagePath?: string[];
  message?: MessageIn;
  queue_if_busy?: boolean;
}

export type RunStatus = 'queued' | 'running' | 'cancelling' | 'completed' | 'cancelled' | 'failed';

export interface InferenceRunOut {
  id: string;
  conversationId: string;
  assistantMessageId: string;
  parentMessageId?: string | null;
  status: RunStatus | string;
  agentSlug?: string | null;
  agentName?: string | null;
  messagePath: string[];
  content?: string | null;
  thinking?: string[] | null;
  rawEvents: RawEvent[];
  errorMessage?: string | null;
  startedAt: string;
  completedAt?: string | null;
  cancelRequestedAt?: string | null;
  updatedAt: string;
  /** Live frames only: approvals the run is paused on. */
  pendingInterrupts?: number;
}

export interface InferenceStartResponse {
  summary: ConversationSummary;
  run: InferenceRunOut;
  message: MessageOut;
  userMessage?: MessageOut | null;
}

export interface QueuedMessage {
  content?: string | null;
  agent_slug: string;
  agent_name?: string | null;
  queued_at: string;
}

export interface QueuedStartResponse {
  queued: true;
  queued_message: QueuedMessage;
}

export interface ResumeDecision {
  decision: 'approve' | 'reject';
  reason?: string | null;
}

export interface ResumePayload {
  interruptId?: string | null;
  decision: 'approve' | 'reject';
  reason?: string | null;
  value?: unknown;
  decisions?: ResumeDecision[];
}

/** One frame of the run socket (`WS /v1/inference/runs/{id}/ws`). */
export type RunFrame =
  | { type: 'snapshot' | 'terminal'; payload: RunSnapshotPayload | null }
  | { type: 'event'; seq: string; payload: RunEventsPayload | RunSnapshotPayload };

export interface RunSnapshotPayload {
  type: 'snapshot' | 'terminal';
  run: InferenceRunOut;
  message?: MessageOut | null;
  summary?: ConversationSummary | null;
}

export interface RunEventsPayload {
  type: 'events';
  run: Partial<InferenceRunOut> & { id: string; updatedAt: string };
  events: RawEvent[];
}

export interface SearchResult {
  kind: 'conversation' | 'message' | 'file';
  id: string;
  conversationId: string;
  agentSlug?: string | null;
  title: string;
  subtitle?: string | null;
  snippet?: string | null;
  updatedAt?: string | null;
}

/** An agent a chat can talk to (agents service `GET /agents`, via the backend when proxied). */
export interface AgentManifest {
  id?: string;
  slug: string;
  name: string;
  description?: string;
  icon?: string;
  default?: boolean;
}

/** A background sub-agent task (`GET /v1/conversations/{id}/tasks`), trimmed to what the UI shows. */
export interface TaskOut {
  task_id: string;
  conversation_id: string;
  parent_task_id?: string | null;
  spawned_by_message_id?: string | null;
  depth?: number;
  name: string;
  description?: string | null;
  model?: string | null;
  /** running / waiting / waiting_children / completed / failed / cancelled… */
  status: string;
  result_preview?: string | null;
  error?: string | null;
  started_at?: string | null;
  settled_at?: string | null;
}
