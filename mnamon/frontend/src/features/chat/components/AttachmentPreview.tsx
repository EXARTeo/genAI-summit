/**
 * The chat's file preview: the shared `FilePreviewPanel` (magenticx `AttachmentPreviewPanel`) fed
 * with a sent attachment (bytes inline or fetched through `GET /v1/attachments/preview/...`, so the
 * anonymous client header goes along) or a composer file (read locally). Download uses the download
 * endpoint; in a chat about a system the header also offers "Save to <system> folder".
 */
import { useMemo } from 'react';
import { FilePreviewPanel } from '@/shared/ui';
import { downloadAttachment, previewFileOf, useAttachmentActions } from '../hooks/useAttachmentActions';
import { useChatUi, type PreviewTarget } from './chatContext';

export function AttachmentPreview({
  target,
  onClose,
}: {
  target: PreviewTarget | null;
  onClose: () => void;
}) {
  const { conversationId } = useChatUi();
  const { extraActions } = useAttachmentActions();
  const file = useMemo(
    () => (target ? previewFileOf(target, conversationId) : null),
    [target, conversationId],
  );
  const sent = target?.kind === 'sent' ? target : null;

  return (
    <FilePreviewPanel
      file={file}
      onClose={onClose}
      actions={sent ? extraActions(sent.attachment) : undefined}
      onDownload={
        sent ? () => downloadAttachment(conversationId, sent.messageId, sent.attachment) : undefined
      }
    />
  );
}
