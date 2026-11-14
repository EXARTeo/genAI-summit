/**
 * Archived chats, in a dialog. magenticx lists them in Settings → Data controls ("Archived
 * conversations": open one, or unarchive it); Mnamon has no settings page, so the sidebar's footer
 * opens this instead. Delete goes through the sidebar's confirm dialog.
 */
import { ArchiveRestore, Trash2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatRelative } from '@/shared/lib/format';
import { Dialog, IconButton, Skeleton } from '@/shared/ui';
import { useConversationList } from '../../hooks/useConversations';
import { chatRoutes } from '../../lib/routes';
import { conversationTitle } from '../../lib/sidebarList';
import type { ConversationSummary } from '../../lib/types';

export function ArchivedChatsDialog({
  open,
  onOpenChange,
  onUnarchive,
  onDelete,
  onNavigate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUnarchive: (c: ConversationSummary) => void;
  onDelete: (c: ConversationSummary) => void;
  onNavigate?: () => void;
}) {
  const archived = useConversationList('archived', { enabled: open });
  const list = archived.data ?? [];

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Archived chats"
      description="Archiving moves a chat out of the sidebar without deleting it."
    >
      <div className="-mx-2 pt-3">
        {archived.isPending ? (
          <div className="space-y-2 px-2">
            {Array.from({ length: 3 }, (_, i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : list.length === 0 ? (
          <p className="px-2 py-8 text-center text-sm text-muted">No archived chats.</p>
        ) : (
          <ul className="flex flex-col">
            {list.map((c) => (
              <li
                key={c.id}
                className="group flex items-center gap-2 rounded-lg px-2 py-1.5 transition-colors hover:bg-hover"
              >
                <Link
                  to={chatRoutes.conversation(c.id)}
                  onClick={() => {
                    onOpenChange(false);
                    onNavigate?.();
                  }}
                  className="min-w-0 flex-1 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="block truncate text-sm text-text">{conversationTitle(c)}</span>
                  <span className="block text-xs text-muted">
                    Archived {formatRelative(c.archivedAt ?? c.updated_at)}
                  </span>
                </Link>
                <IconButton
                  label="Unarchive"
                  size="icon-sm"
                  icon={<ArchiveRestore />}
                  onClick={() => onUnarchive(c)}
                />
                <IconButton
                  label="Delete"
                  size="icon-sm"
                  icon={<Trash2 />}
                  className="hover:text-danger"
                  onClick={() => onDelete(c)}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </Dialog>
  );
}
