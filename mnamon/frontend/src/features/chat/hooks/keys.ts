export const chatKeys = {
  all: ['chat'] as const,
  lists: () => ['chat', 'list'] as const,
  list: (filter: 'recent' | 'pinned' | 'archived') => ['chat', 'list', filter] as const,
  detail: (id: string) => ['chat', 'conversation', id] as const,
  /** The conversation's background tasks (`GET /v1/conversations/{id}/tasks`). */
  tasks: (id: string) => ['chat', 'tasks', id] as const,
  search: (q: string) => ['chat', 'search', q] as const,
  agents: () => ['chat', 'agents'] as const,
  subject: (systemId?: string | null, auditId?: string | null) =>
    ['chat', 'subject', systemId ?? '', auditId ?? ''] as const,
};
