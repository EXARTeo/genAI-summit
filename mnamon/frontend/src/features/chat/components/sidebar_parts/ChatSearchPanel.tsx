/*
 * magenticx's `features/search/components/SearchPanel.tsx`, built on the same cmdk + Radix Dialog
 * pair as the shell's ⌘K palette (src/app/CommandPalette.tsx) so it gets arrow-key navigation and a
 * focus trap. Server search (`GET /v1/search`) over titles, messages and file names, grouped by kind;
 * with no query it lists the recent chats.
 */
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { Command } from 'cmdk';
import { FileText, MessageSquare, MessagesSquare, Search, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Skeleton } from '@/shared/ui';
import { useChatSearch } from '../../hooks/useConversations';
import { chatRoutes } from '../../lib/routes';
import { asSearchResult, groupSearchResults, plainSnippet } from '../../lib/sidebarList';
import type { ConversationSummary, SearchResult } from '../../lib/types';

const MIN_QUERY = 2;

const groupCls =
  '[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-2xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-muted';
const itemCls =
  'flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 text-left outline-none transition-colors aria-selected:bg-hover';

function ResultIcon({ kind }: { kind: SearchResult['kind'] }) {
  const Icon = kind === 'file' ? FileText : kind === 'message' ? MessageSquare : MessagesSquare;
  return (
    <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
      <Icon className="size-4" />
    </span>
  );
}

const KIND_HINT: Record<SearchResult['kind'], string> = {
  conversation: 'Chat',
  message: 'Message',
  file: 'File',
};

function ResultItem({ result, onSelect }: { result: SearchResult; onSelect: (r: SearchResult) => void }) {
  return (
    <Command.Item value={`${result.kind}-${result.id}`} onSelect={() => onSelect(result)} className={itemCls}>
      <ResultIcon kind={result.kind} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-text">{result.title}</span>
        <span className="block truncate text-xs text-muted">
          {plainSnippet(result.snippet) || result.subtitle || KIND_HINT[result.kind]}
        </span>
      </span>
    </Command.Item>
  );
}

function SkeletonRows() {
  return (
    <div className="space-y-4 px-2 py-3" aria-label="Searching">
      {Array.from({ length: 3 }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="size-9 shrink-0 rounded-xl" />
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className="h-3.5 w-24" />
            <Skeleton className="h-3.5 w-full max-w-[150px]" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ChatSearchPanel({
  open,
  onOpenChange,
  recent,
  onNavigate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Shown while the query is empty ("Recent chats"). */
  recent: ConversationSummary[];
  onNavigate?: () => void;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 200);
    return () => clearTimeout(t);
  }, [query]);
  useEffect(() => {
    if (!open) {
      setQuery('');
      setDebounced('');
    }
  }, [open]);

  const search = useChatSearch(debounced);
  const hasQuery = debounced.length >= MIN_QUERY;
  const typing = query.trim().length >= MIN_QUERY && query.trim() !== debounced;
  const loading = hasQuery && (search.isPending || typing);
  const groups = useMemo(() => groupSearchResults(search.data ?? []), [search.data]);
  const recentResults = useMemo(() => recent.slice(0, 8).map(asSearchResult), [recent]);

  const select = (r: SearchResult) => {
    onOpenChange(false);
    onNavigate?.();
    navigate(chatRoutes.conversation(r.conversationId));
  };

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-background/60 backdrop-blur-sm data-[state=open]:animate-[overlay-in_160ms_ease-out]" />
        <DialogPrimitive.Content
          // Focus goes back to nothing in particular: the shortcut's target is a hidden input that
          // would reopen the panel on focus.
          onCloseAutoFocus={(e) => e.preventDefault()}
          className="fixed left-1/2 top-[12vh] z-50 flex max-h-[min(38rem,calc(100svh-2rem))] w-[min(34rem,calc(100vw-2rem))] -translate-x-1/2 flex-col overflow-hidden rounded-xl border border-border/70 bg-surface text-text shadow-pop data-[state=open]:animate-[dialog-in_200ms_cubic-bezier(0.16,1,0.3,1)]"
        >
          <DialogPrimitive.Title className="sr-only">Search chats</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">
            Search chat titles, messages and file names
          </DialogPrimitive.Description>
          <Command shouldFilter={false} loop className="flex min-h-0 flex-col">
            <div className="flex items-center gap-2 border-b border-border/70 px-3 py-2">
              <Search className="size-4 shrink-0 text-muted" />
              <Command.Input
                autoFocus
                value={query}
                onValueChange={setQuery}
                placeholder="Search chats, messages and files…"
                aria-label="Search query"
                spellCheck={false}
                className="h-8 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
              />
              <DialogPrimitive.Close
                aria-label="Close search"
                className="grid size-7 shrink-0 place-items-center rounded-md text-muted transition-colors hover:bg-hover hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X className="size-4" />
              </DialogPrimitive.Close>
            </div>
            <Command.List className="min-h-[20rem] overflow-y-auto p-2">
              {loading ? (
                <SkeletonRows />
              ) : hasQuery && search.isError ? (
                <div className="flex min-h-[10rem] items-center justify-center px-4 text-center text-sm text-danger">
                  Search failed. Try again.
                </div>
              ) : !hasQuery ? (
                recentResults.length > 0 ? (
                  <Command.Group heading="Recent chats" className={groupCls}>
                    {recentResults.map((r) => (
                      <ResultItem key={r.id} result={r} onSelect={select} />
                    ))}
                  </Command.Group>
                ) : (
                  <div className="flex min-h-[10rem] items-center justify-center px-4 text-center text-sm text-muted">
                    Search chat titles, messages and file names.
                  </div>
                )
              ) : groups.length === 0 ? (
                <div className="flex min-h-[10rem] items-center justify-center px-4 text-center text-sm text-muted">
                  No results for “{debounced}”
                </div>
              ) : (
                groups.map((g) => (
                  <Command.Group key={g.kind} heading={g.label} className={groupCls}>
                    {g.items.map((r) => (
                      <ResultItem key={`${r.kind}-${r.id}`} result={r} onSelect={select} />
                    ))}
                  </Command.Group>
                ))
              )}
            </Command.List>
          </Command>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
