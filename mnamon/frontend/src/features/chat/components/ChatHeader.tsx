/**
 * The chat's header row (magenticx `ChatHeader.tsx`), shown in the app's top bar: the agent
 * picker on the left, then the conversation's title (quiet) and what it is about (a link to the
 * system); the conversation's actions (pin, archive, delete) and a new chat on the right.
 * magenticx's Share and private-chat controls have no backend here and are left out.
 */
import { Archive, MoreHorizontal, Pin, PinOff, SquarePen, Target, Trash2 } from 'lucide-react';
import { forwardRef } from 'react';
import { Link } from 'react-router-dom';
import { DropdownMenu, IconButton } from '@/shared/ui';
import type { AgentManifest } from '../lib/types';
import { AgentPicker, type AgentPickerHandle } from './AgentPicker';

export interface ChatHeaderProps {
  agents: AgentManifest[];
  agent: AgentManifest | null;
  onAgentChange: (agent: AgentManifest) => void;
  /** The open conversation's title (none for a new chat). */
  title?: string | null;
  /** What the chat is about: label + the system it links to. */
  subject?: { label: string; systemId: string | null } | null;
  /** The open conversation's actions; left out for a new chat. */
  conversation?: {
    pinned: boolean;
    onPin: () => void;
    onArchive: () => void;
    onDelete: () => void;
  } | null;
  onNewChat: () => void;
}

export const ChatHeader = forwardRef<AgentPickerHandle, ChatHeaderProps>(function ChatHeader(
  { agents, agent, onAgentChange, title, subject, conversation, onNewChat },
  pickerRef,
) {
  return (
    <div className="flex min-w-0 flex-1 items-center gap-1.5 md:gap-2" data-chat-header>
      <AgentPicker ref={pickerRef} agents={agents} agent={agent} onPick={onAgentChange} />
      {title && (
        <span className="hidden min-w-0 truncate text-sm text-muted md:block" title={title}>
          {title}
        </span>
      )}
      {subject &&
        (subject.systemId ? (
          <Link
            to={`/systems/${encodeURIComponent(subject.systemId)}`}
            className="hidden shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-2xs text-muted transition-colors hover:bg-hover hover:text-text sm:inline-flex"
          >
            <Target className="size-3" aria-hidden /> {subject.label}
          </Link>
        ) : (
          <span className="hidden shrink-0 items-center gap-1 px-1.5 text-2xs text-muted sm:inline-flex">
            <Target className="size-3" aria-hidden /> {subject.label}
          </span>
        ))}
      <div className="ml-auto flex shrink-0 items-center gap-0.5">
        {conversation && (
          <>
            <IconButton
              label="New chat (Ctrl+Shift+O)"
              icon={<SquarePen />}
              className="md:hidden"
              onClick={onNewChat}
            />
            <DropdownMenu
              trigger={<IconButton label="Conversation actions" icon={<MoreHorizontal />} />}
              items={[
                {
                  label: conversation.pinned ? 'Unpin' : 'Pin',
                  icon: conversation.pinned ? <PinOff /> : <Pin />,
                  onSelect: conversation.onPin,
                },
                { label: 'Archive', icon: <Archive />, onSelect: conversation.onArchive },
                { type: 'separator' },
                { label: 'Delete', icon: <Trash2 />, danger: true, onSelect: conversation.onDelete },
              ]}
            />
          </>
        )}
      </div>
    </div>
  );
});
