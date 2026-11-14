/** react-query wrappers for the conversation list, one conversation, search and the agents. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/shared/lib/api';
import {
  deleteConversation,
  getConversation,
  listAgents,
  listArchived,
  listConversations,
  listPinned,
  renameConversation,
  searchChats,
  setArchived,
  setPinned,
} from '../handlers/chat';
import type { ConversationSummary } from '../lib/types';
import { chatKeys } from './keys';

export function useConversationList(filter: 'recent' | 'pinned' | 'archived') {
  return useQuery({
    queryKey: chatKeys.list(filter),
    queryFn: () =>
      filter === 'pinned' ? listPinned() : filter === 'archived' ? listArchived() : listConversations(),
    select: (page) => page.items,
  });
}

export function useConversation(id: string | null | undefined) {
  return useQuery({
    queryKey: chatKeys.detail(id ?? ''),
    queryFn: () => getConversation(id as string),
    enabled: Boolean(id),
    staleTime: 60_000,
  });
}

export function useAgents() {
  return useQuery({ queryKey: chatKeys.agents(), queryFn: listAgents, staleTime: 5 * 60_000 });
}

export function useChatSearch(q: string) {
  const query = q.trim();
  return useQuery({
    queryKey: chatKeys.search(query),
    queryFn: ({ signal }) => searchChats(query, signal),
    enabled: query.length >= 2,
    staleTime: 10_000,
  });
}

/** What the chat is about: the system's name and the audit id, for the composer chip. */
export function useChatSubject(systemId?: string | null, auditId?: string | null) {
  return useQuery({
    queryKey: chatKeys.subject(systemId, auditId),
    enabled: Boolean(systemId || auditId),
    staleTime: 5 * 60_000,
    queryFn: async () => {
      let resolvedSystemId = systemId ?? null;
      if (!resolvedSystemId && auditId) {
        const audit = await api
          .get<{ system_id?: string; systemId?: string }>(`/v1/audits/${encodeURIComponent(auditId)}`)
          .catch(() => null);
        resolvedSystemId = audit?.systemId ?? audit?.system_id ?? null;
      }
      const system = resolvedSystemId
        ? await api
            .get<{ id: string; name: string }>(`/v1/systems/${encodeURIComponent(resolvedSystemId)}`)
            .catch(() => null)
        : null;
      return {
        systemId: resolvedSystemId,
        systemName: system?.name ?? resolvedSystemId,
        auditId: auditId ?? null,
      };
    },
  });
}

/** Rename / pin / archive / delete, with the lists refreshed after. */
export function useConversationActions() {
  const qc = useQueryClient();
  const refresh = (summary?: ConversationSummary | void) => {
    void qc.invalidateQueries({ queryKey: chatKeys.lists() });
    if (summary && 'id' in summary) {
      qc.setQueryData(chatKeys.detail(summary.id), (prev: object | undefined) =>
        prev ? { ...prev, ...summary } : prev,
      );
    }
  };
  return {
    rename: useMutation({
      mutationFn: (v: { id: string; title: string }) => renameConversation(v.id, v.title),
      onSuccess: refresh,
    }),
    pin: useMutation({
      mutationFn: (v: { id: string; pinned: boolean }) => setPinned(v.id, v.pinned),
      onSuccess: refresh,
    }),
    archive: useMutation({
      mutationFn: (v: { id: string; archived: boolean }) => setArchived(v.id, v.archived),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: string) => deleteConversation(id),
      onSuccess: (_d, id) => {
        qc.removeQueries({ queryKey: chatKeys.detail(id) });
        refresh();
      },
    }),
  };
}
