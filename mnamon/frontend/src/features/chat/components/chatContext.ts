import { createContext, useContext } from 'react';
import type { PendingAttachment } from '../lib/attachments';
import type { AttachmentOut } from '../lib/types';

/** What a preview opens: a sent attachment (fetched from the backend) or a composer file. */
export type PreviewTarget =
  | { kind: 'sent'; attachment: AttachmentOut; messageId: string }
  | { kind: 'pending'; attachment: PendingAttachment };

export interface ChatUi {
  conversationId: string | null;
  /** The system this chat is about: attachments can be saved to its folder. */
  systemId: string | null;
  systemName: string | null;
  openPreview: (target: PreviewTarget) => void;
}

export const ChatUiContext = createContext<ChatUi>({
  conversationId: null,
  systemId: null,
  systemName: null,
  openPreview: () => undefined,
});

export const useChatUi = () => useContext(ChatUiContext);
