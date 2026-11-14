/** Chat UI paths and backend API paths. */

export const chatRoutes = {
  root: '/chat',
  conversation: (id: string) => `/chat/${encodeURIComponent(id)}`,
  /** A new chat about a system and/or an audit ("Discussing: CV Screener"). */
  about: (opts: { systemId?: string | null; auditId?: string | null }) => {
    const q = new URLSearchParams();
    if (opts.systemId) q.set('system', opts.systemId);
    if (opts.auditId) q.set('audit', opts.auditId);
    const s = q.toString();
    return `/chat${s ? `?${s}` : ''}`;
  },
};

const enc = encodeURIComponent;

export const chatApi = {
  conversations: '/v1/conversations',
  pinned: '/v1/conversations/pinned',
  archived: '/v1/conversations/archived',
  conversation: (id: string) => `/v1/conversations/${enc(id)}`,
  title: (id: string) => `/v1/conversations/${enc(id)}/title`,
  archive: (id: string) => `/v1/conversations/${enc(id)}/archive`,
  unarchive: (id: string) => `/v1/conversations/${enc(id)}/unarchive`,
  pin: (id: string) => `/v1/conversations/${enc(id)}/pin`,
  unpin: (id: string) => `/v1/conversations/${enc(id)}/unpin`,
  fork: (id: string) => `/v1/conversations/${enc(id)}/fork`,
  tasks: (id: string) => `/v1/conversations/${enc(id)}/tasks`,
  like: (conv: string, msg: string) => `/v1/messages/${enc(conv)}/${enc(msg)}/like`,
  dislike: (conv: string, msg: string) => `/v1/messages/${enc(conv)}/${enc(msg)}/dislike`,
  start: '/v1/inference/runs/start',
  runs: '/v1/inference/runs',
  cancel: (runId: string) => `/v1/inference/runs/${enc(runId)}/cancel`,
  resume: (runId: string) => `/v1/inference/runs/${enc(runId)}/resume`,
  runSocket: (runId: string) => `/v1/inference/runs/${enc(runId)}/ws`,
  conversationSocket: (id: string) => `/v1/inference/conversations/${enc(id)}/ws`,
  queued: (id: string) => `/v1/inference/conversations/${enc(id)}/queued-message`,
  cancelTask: (taskId: string) => `/v1/tasks/${enc(taskId)}/cancel`,
  search: '/v1/search',
  download: (conv: string, msg: string, blob: string) =>
    `/v1/attachments/download/${enc(conv)}/${enc(msg)}/${enc(blob)}`,
  preview: (conv: string, msg: string, blob: string) =>
    `/v1/attachments/preview/${enc(conv)}/${enc(msg)}/${enc(blob)}`,
  saveToSystem: (systemId: string) => `/v1/systems/${enc(systemId)}/files/from-attachment`,
  /** The agents catalog (filtered to chat agents by lib/agents.ts). */
  agents: '/v1/agents',
};
