/**
 * The conversation list in the shell's sidebar slot (magenticx `ChatSidebar.tsx`): a "New chat" and
 * a "Search chats" row, then two folding sections, Pinned (newest pin first) and Chats (most recent
 * first, paged in as the list scrolls), and an "Archived" footer row. Rows show the title only; the
 * open chat wears a highlight with an accent bar; a chat whose agent is working shows a spinner at
 * the row end; "⋯" opens Rename (inline), Pin/Unpin, Archive and Delete (confirmed).
 */
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { Archive, MessageSquare, TextSearch } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type UIEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMediaQuery } from '@/shared/hooks/useMediaQuery';
import { INTERACTIVE_SURFACE } from '@/shared/lib/consts/ui';
import { cn } from '@/shared/lib/utils';
import { useUiStore } from '@/shared/stores/ui';
import { Button, Dialog, Skeleton, toast } from '@/shared/ui';
import { useRunStore } from '../hooks/runStore';
import { useConversationActions, useConversationList, useConversationPages } from '../hooks/useConversations';
import { useChatSearchPanel, useSectionOpen } from '../hooks/useSidebarUi';
import { chatRoutes } from '../lib/routes';
import { isActiveRun } from '../lib/runState';
import { conversationTitle, flattenPages, isNearBottom, sortPinned } from '../lib/sidebarList';
import { sectionListMotion } from '../lib/sidebarMotion';
import type { ConversationSummary } from '../lib/types';
import { ArchivedChatsDialog } from './sidebar_parts/ArchivedChatsDialog';
import { ChatSearchPanel } from './sidebar_parts/ChatSearchPanel';
import { ConversationRow } from './sidebar_parts/ConversationRow';
import { NewChatIcon } from './sidebar_parts/NewChatIcon';
import { SidebarSection, SidebarSectionRows } from './sidebar_parts/SidebarSection';

/** The rail's row recipe (src/app/Sidebar.tsx), so these rows line up with the nav above. */
const TOP_ROW = `group/nav relative flex h-9 w-full items-center gap-1 rounded-xl px-1.5 text-sm text-text/90 outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring ${INTERACTIVE_SURFACE}`;
const ICON_BOX = 'grid size-9 shrink-0 place-items-center';
const ICON = 'transition-transform duration-300 ease-out motion-safe:group-hover/nav:scale-110';

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);

const errorText = (e: unknown) => (e instanceof Error && e.message ? e.message : 'Something went wrong.');

function RowsSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="space-y-2 px-2.5 py-1.5" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className="h-4" style={{ width: `${80 - ((i * 17) % 35)}%` }} />
      ))}
    </div>
  );
}

/** Ids of the conversations whose agent is working right now (live runs in this tab). */
function useLiveConversationIds(): Set<string> {
  const key = useRunStore((s) =>
    Object.values(s.runs)
      .filter((r) => isActiveRun(r))
      .map((r) => r.conversationId)
      .sort()
      .join('|'),
  );
  return useMemo(() => new Set(key ? key.split('|') : []), [key]);
}

export function ChatSidebar({ activeId, className }: { activeId: string | null; className?: string }) {
  const navigate = useNavigate();
  const reduceMotion = useReducedMotion();
  const setMobileNavOpen = useUiStore((s) => s.setMobileNavOpen);
  const closeDrawer = useCallback(() => setMobileNavOpen(false), [setMobileNavOpen]);

  const pinnedQuery = useConversationList('pinned');
  const pages = useConversationPages();
  const actions = useConversationActions();
  const liveIds = useLiveConversationIds();
  const wide = useMediaQuery('(min-width: 1024px)');

  const [pinnedOpen, togglePinned] = useSectionOpen('pinned');
  const [chatsOpen, toggleChats] = useSectionOpen('chats');
  const searchOpen = useChatSearchPanel((s) => s.open);
  const setSearchOpen = useChatSearchPanel((s) => s.setOpen);
  const [archivedOpen, setArchivedOpen] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null);

  const pinned = useMemo(() => sortPinned(pinnedQuery.data ?? []), [pinnedQuery.data]);
  const chats = useMemo(() => {
    const pinnedIds = new Set(pinned.map((c) => c.id));
    return flattenPages(pages.data?.pages).filter((c) => !pinnedIds.has(c.id));
  }, [pages.data, pinned]);

  // Page in more as the Chats list nears its end, and fill a short list until it scrolls.
  const listRef = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = pages;
  const loadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);
  const onListScroll = (e: UIEvent<HTMLDivElement>) => {
    if (chatsOpen && isNearBottom(e.currentTarget)) loadMore();
  };
  useEffect(() => {
    const el = listRef.current;
    if (!chatsOpen || !el || !hasNextPage || isFetchingNextPage) return;
    if (el.scrollHeight <= el.clientHeight + 4) loadMore();
  }, [chatsOpen, chats.length, hasNextPage, isFetchingNextPage, loadMore]);

  const leaveIfOpen = (id: string) => {
    if (id === activeId) navigate(chatRoutes.root);
  };

  const rowProps = (c: ConversationSummary, index: number) => ({
    conversation: c,
    index,
    active: c.id === activeId,
    working: liveIds.has(c.id) || Boolean(c.isStreaming || c.hasActiveTasks),
    renaming: renamingId === c.id,
    onStartRename: () => setRenamingId(c.id),
    onCancelRename: () => setRenamingId((cur) => (cur === c.id ? null : cur)),
    onRename: (title: string) =>
      actions.rename.mutateAsync({ id: c.id, title }).then(
        () => setRenamingId(null),
        (e: unknown) => {
          toast.error(`Couldn't rename the chat. ${errorText(e)}`);
          throw e;
        },
      ),
    onTogglePin: () =>
      actions.pin.mutate(
        { id: c.id, pinned: !c.isPinned },
        { onError: (e) => toast.error(`Couldn't ${c.isPinned ? 'unpin' : 'pin'} the chat. ${errorText(e)}`) },
      ),
    onArchive: () =>
      actions.archive.mutate(
        { id: c.id, archived: true },
        {
          onSuccess: () => {
            toast.success('Chat archived', {
              description: 'Find it under Archived at the bottom of the list.',
            });
            leaveIfOpen(c.id);
          },
          onError: (e) => toast.error(`Couldn't archive the chat. ${errorText(e)}`),
        },
      ),
    onDelete: () => setDeleting(c),
    onNavigate: closeDrawer,
    menuSide: wide ? ('right' as const) : ('bottom' as const),
  });

  const showSkeleton = pages.isPending;
  const showEmpty = !showSkeleton && !pages.isError && chats.length === 0 && pinned.length === 0;
  const showAllPinnedHint = !showSkeleton && !showEmpty && chats.length === 0 && !hasNextPage;

  return (
    <aside className={cn('flex h-full min-h-0 flex-col', className)} aria-label="Chats">
      <div className="flex shrink-0 flex-col pt-1">
        <Link to={chatRoutes.root} onClick={closeDrawer} className={cn(TOP_ROW, 'font-medium text-text')}>
          <span className={ICON_BOX}>
            <NewChatIcon className={cn(ICON, 'motion-safe:group-hover/nav:-rotate-12')} />
          </span>
          New chat
        </Link>
        <button type="button" onClick={() => setSearchOpen(true)} className={TOP_ROW}>
          <span className={ICON_BOX}>
            <TextSearch className={cn('size-[18px]', ICON)} />
          </span>
          <span className="flex-1 text-left">Search chats</span>
          <kbd className="mr-1.5 rounded-md border border-border bg-surface-muted px-1.5 font-sans text-2xs text-muted opacity-0 transition-opacity group-hover/nav:opacity-100 group-focus-visible/nav:opacity-100">
            {isMac ? '⇧⌘S' : 'Ctrl ⇧ S'}
          </kbd>
        </button>
        {/* Ctrl/⌘+Shift+S and the /search command focus `input[aria-label="Search chats"]`
            (ChatWorkspace); focusing this hidden input opens the search panel. */}
        <input
          aria-label="Search chats"
          aria-hidden="true"
          tabIndex={-1}
          readOnly
          onFocus={(e) => {
            e.currentTarget.blur();
            setSearchOpen(true);
          }}
          className="sr-only"
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col pt-2">
        <AnimatePresence initial={false}>
          {pinned.length > 0 && (
            <motion.div key="pinned-section" className="shrink-0" {...sectionListMotion(reduceMotion)}>
              <SidebarSection
                label="Pinned"
                open={pinnedOpen}
                onToggle={togglePinned}
                listId="chat-sidebar-pinned"
                // Capped so a long pin list scrolls on its own and never pushes Chats off screen.
                listClassName="max-h-[30dvh]"
              >
                <SidebarSectionRows>
                  {pinned.map((c, i) => (
                    <ConversationRow key={c.id} {...rowProps(c, i)} />
                  ))}
                </SidebarSectionRows>
              </SidebarSection>
            </motion.div>
          )}
        </AnimatePresence>
        <SidebarSection
          label="Chats"
          open={chatsOpen}
          onToggle={toggleChats}
          listId="chat-sidebar-chats"
          className="min-h-0 flex-1"
          listClassName="min-h-0 flex-1 pb-3"
          listRef={listRef}
          onScroll={onListScroll}
        >
          {showSkeleton ? (
            <RowsSkeleton />
          ) : pages.isError ? (
            <p className="px-2.5 py-2 text-xs text-danger">
              Couldn&apos;t load your chats.{' '}
              <button type="button" className="underline" onClick={() => void pages.refetch()}>
                Retry
              </button>
            </p>
          ) : showEmpty ? (
            <div className="flex flex-col items-center justify-center gap-1.5 rounded-lg py-10 text-center text-muted">
              <MessageSquare className="mb-2 size-7 opacity-60" aria-hidden />
              <p className="text-sm">No chats yet</p>
            </div>
          ) : (
            <SidebarSectionRows>
              {chats.map((c, i) => (
                <ConversationRow key={c.id} {...rowProps(c, i)} />
              ))}
            </SidebarSectionRows>
          )}
          {showAllPinnedHint && (
            <p className="px-2.5 py-2 text-xs text-muted">Chats you haven&apos;t pinned show up here.</p>
          )}
          {isFetchingNextPage && <RowsSkeleton count={2} />}
        </SidebarSection>
      </div>

      <div className="shrink-0 border-t border-border/60 py-1">
        <button
          type="button"
          onClick={() => setArchivedOpen(true)}
          className={cn(TOP_ROW, 'h-8 text-[13px] text-muted hover:text-text')}
        >
          <span className={ICON_BOX}>
            <Archive className={cn('size-4', ICON)} />
          </span>
          Archived
        </button>
      </div>

      <ChatSearchPanel
        open={searchOpen}
        onOpenChange={setSearchOpen}
        recent={[...pinned, ...chats]}
        onNavigate={closeDrawer}
      />

      <ArchivedChatsDialog
        open={archivedOpen}
        onOpenChange={setArchivedOpen}
        onNavigate={closeDrawer}
        onUnarchive={(c) =>
          actions.archive.mutate(
            { id: c.id, archived: false },
            {
              onSuccess: () => toast.success('Chat restored to the list'),
              onError: (e) => toast.error(`Couldn't unarchive the chat. ${errorText(e)}`),
            },
          )
        }
        onDelete={setDeleting}
      />

      <Dialog
        open={Boolean(deleting)}
        onOpenChange={(open) => !open && setDeleting(null)}
        size="sm"
        title="Delete this chat?"
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
                    toast.success('Chat deleted');
                    leaveIfOpen(id);
                  },
                  onError: (e) => toast.error(`Couldn't delete the chat. ${errorText(e)}`),
                });
              }}
            >
              Delete
            </Button>
          </>
        }
      >
        <p className="pt-4 text-sm text-muted">
          “{deleting ? conversationTitle(deleting) : ''}” and its files are deleted for good.
        </p>
      </Dialog>
    </aside>
  );
}
