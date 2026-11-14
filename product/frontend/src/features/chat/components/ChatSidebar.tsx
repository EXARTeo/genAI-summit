/**
 * The conversation list (magenticx `ChatSidebar.tsx` + `search/SearchPanel`): new chat, search
 * over titles, messages and file names (`GET /v1/search`), pinned and recent chats grouped by
 * day, an archive view, and a row menu (rename inline, pin, archive, delete). A chat whose agent
 * is still working shows a spinner.
 */
import {
  Archive,
  ArchiveRestore,
  FileText,
  Loader2,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Search,
  Target,
  Trash2,
  X,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { cn } from '@/shared/lib/utils';
import { Button, Dialog, DropdownMenu, IconButton, Skeleton } from '@/shared/ui';
import { useChatSearch, useConversationActions, useConversationList } from '../hooks/useConversations';
import { useRunStore } from '../hooks/runStore';
import { chatRoutes } from '../lib/routes';
import { isActiveRun } from '../lib/runState';
import type { ConversationSummary } from '../lib/types';

function dayGroup(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  const t = d.getTime();
  if (t >= start) return 'Today';
  if (t >= start - 86_400_000) return 'Yesterday';
  if (t >= start - 7 * 86_400_000) return 'Previous 7 days';
  return 'Older';
}

function Row({
  c,
  active,
  onDelete,
}: {
  c: ConversationSummary;
  active: boolean;
  onDelete: (c: ConversationSummary) => void;
}) {
  const actions = useConversationActions();
  const live = useRunStore((s) =>
    Object.values(s.runs).some((r) => r.conversationId === c.id && isActiveRun(r)),
  );
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(c.title ?? '');
  const working = live || c.isStreaming || c.hasActiveTasks;

  if (renaming) {
    return (
      <input
        autoFocus
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onBlur={() => setRenaming(false)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setRenaming(false);
          if (e.key === 'Enter' && title.trim()) {
            actions.rename.mutate({ id: c.id, title: title.trim() });
            setRenaming(false);
          }
        }}
        aria-label="Chat title"
        className="h-8 w-full rounded-md border border-primary/50 bg-background px-2 text-sm outline-none"
      />
    );
  }
  return (
    <div
      className={cn(
        'group relative flex h-8 items-center rounded-md text-sm transition-colors',
        active ? 'bg-surface-muted text-text' : 'text-muted hover:bg-surface-muted/60 hover:text-text',
      )}
    >
      <Link
        to={chatRoutes.conversation(c.id)}
        className="flex min-w-0 flex-1 items-center gap-2 px-2"
        title={c.title ?? undefined}
      >
        {working ? (
          <Loader2 className="size-3.5 shrink-0 animate-spin text-primary" aria-label="Working" />
        ) : c.systemId ? (
          <Target className="size-3.5 shrink-0 opacity-60" />
        ) : null}
        <span className="truncate">{c.title || 'Untitled chat'}</span>
      </Link>
      <div
        className={cn(
          'pr-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100',
          active && 'opacity-100',
        )}
      >
        <DropdownMenu
          trigger={
            <IconButton label="Chat actions" size="icon-sm" icon={<MoreHorizontal />} tooltip={false} />
          }
          items={[
            { label: 'Rename', icon: <Pencil />, onSelect: () => setRenaming(true) },
            {
              label: c.isPinned ? 'Unpin' : 'Pin',
              icon: c.isPinned ? <PinOff /> : <Pin />,
              onSelect: () => actions.pin.mutate({ id: c.id, pinned: !c.isPinned }),
            },
            {
              label: c.isArchived ? 'Unarchive' : 'Archive',
              icon: c.isArchived ? <ArchiveRestore /> : <Archive />,
              onSelect: () => actions.archive.mutate({ id: c.id, archived: !c.isArchived }),
            },
            { type: 'separator' },
            { label: 'Delete', icon: <Trash2 />, danger: true, onSelect: () => onDelete(c) },
          ]}
        />
      </div>
    </div>
  );
}

export function ChatSidebar({ activeId, className }: { activeId: string | null; className?: string }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [archived, setArchived] = useState(false);
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query), 200);
    return () => clearTimeout(t);
  }, [query]);
  const recent = useConversationList(archived ? 'archived' : 'recent');
  const pinned = useConversationList('pinned');
  const search = useChatSearch(debounced);
  const actions = useConversationActions();

  const groups = useMemo(() => {
    const out: [string, ConversationSummary[]][] = [];
    for (const c of recent.data ?? []) {
      const g = archived ? 'Archived' : dayGroup(c.updated_at);
      const last = out[out.length - 1];
      if (last?.[0] === g) last[1].push(c);
      else out.push([g, [c]]);
    }
    return out;
  }, [recent.data, archived]);

  const searching = debounced.trim().length >= 2;

  return (
    <aside className={cn('flex min-h-0 flex-1 flex-col', className)} aria-label="Chats">
      <div className="space-y-2 px-1 pb-2 pt-3">
        <Button
          className="w-full justify-start"
          variant="secondary"
          leftIcon={<Plus />}
          onClick={() => navigate(chatRoutes.root)}
        >
          New chat
        </Button>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
          <input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats"
            aria-label="Search chats"
            className="h-8 w-full rounded-lg border border-border bg-background pl-8 pr-7 text-sm outline-none placeholder:text-muted focus:border-primary/50"
          />
          {query && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => setQuery('')}
              className="absolute right-1.5 top-1/2 grid size-5 -translate-y-1/2 place-items-center rounded text-muted hover:text-text"
            >
              <X className="size-3" />
            </button>
          )}
        </div>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto pb-3">
        {searching ? (
          <div className="space-y-0.5">
            <div className="px-2 pb-1 pt-2 text-2xs font-medium text-muted">Results</div>
            {search.isPending && <Skeleton className="mx-2 h-8" />}
            {search.data?.length === 0 && (
              <p className="px-2 py-2 text-xs text-muted">Nothing matches “{debounced}”.</p>
            )}
            {search.data?.map((r) => (
              <Link
                key={`${r.kind}-${r.id}`}
                to={chatRoutes.conversation(r.conversationId)}
                className="flex gap-2 rounded-md px-2 py-1.5 text-sm text-muted hover:bg-surface-muted hover:text-text"
              >
                {r.kind === 'file' ? (
                  <FileText className="mt-0.5 size-3.5 shrink-0" />
                ) : (
                  <MessageSquare className="mt-0.5 size-3.5 shrink-0" />
                )}
                <span className="min-w-0">
                  <span className="block truncate text-text">{r.title}</span>
                  {r.snippet && <span className="line-clamp-2 text-2xs">{r.snippet}</span>}
                </span>
              </Link>
            ))}
          </div>
        ) : (
          <>
            {!archived && (pinned.data?.length ?? 0) > 0 && (
              <div className="space-y-0.5">
                <div className="px-2 pb-1 pt-2 text-2xs font-medium text-muted">Pinned</div>
                {pinned.data?.map((c) => (
                  <Row key={c.id} c={c} active={c.id === activeId} onDelete={setDeleting} />
                ))}
              </div>
            )}
            {recent.isPending && (
              <div className="space-y-1.5 px-2 pt-3">
                {Array.from({ length: 5 }, (_, i) => (
                  <Skeleton key={i} className="h-6" />
                ))}
              </div>
            )}
            {groups.map(([label, list]) => (
              <div key={label} className="space-y-0.5">
                <div className="px-2 pb-1 pt-3 text-2xs font-medium text-muted">{label}</div>
                {list.map((c) => (
                  <Row key={c.id} c={c} active={c.id === activeId} onDelete={setDeleting} />
                ))}
              </div>
            ))}
            {recent.data?.length === 0 && (
              <p className="px-2 py-3 text-xs text-muted">
                {archived ? 'No archived chats.' : 'No chats yet.'}
              </p>
            )}
          </>
        )}
      </nav>

      <div className="border-t border-border/60 pt-1">
        <button
          type="button"
          onClick={() => setArchived((a) => !a)}
          className="flex h-8 w-full items-center gap-2 rounded-md px-2 text-xs text-muted hover:bg-surface-muted hover:text-text"
        >
          {archived ? <MessageSquare className="size-3.5" /> : <Archive className="size-3.5" />}
          {archived ? 'Back to chats' : 'Archived chats'}
        </button>
      </div>

      <Dialog
        open={Boolean(deleting)}
        onOpenChange={(open) => !open && setDeleting(null)}
        title="Delete this chat?"
        description={`“${deleting?.title ?? 'Untitled chat'}” and its files are deleted for good.`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={actions.remove.isPending}
              onClick={() => {
                if (!deleting) return;
                const id = deleting.id;
                actions.remove.mutate(id, {
                  onSuccess: () => {
                    setDeleting(null);
                    if (id === activeId) navigate(chatRoutes.root);
                  },
                });
              }}
            >
              Delete
            </Button>
          </>
        }
      >
        {null}
      </Dialog>
    </aside>
  );
}
