/**
 * What the chat can do with a sent or generated file, for the shared file chip, image grid and
 * preview: its bytes (`load`, inline base64 or `GET /v1/attachments/preview/...` with the client
 * header), Download (`GET /v1/attachments/download/...`) and, in a chat about a system,
 * "Save to <system> folder" (`POST /v1/systems/{id}/files/from-attachment`).
 */
import { FolderInput } from 'lucide-react';
import { useState } from 'react';
import { blobFromBase64, downloadName, triggerBrowserDownload } from '@/shared/lib/files';
import { toast, type FileAction, type PreviewFile } from '@/shared/ui';
import { downloadAttachmentBlob, previewAttachmentBlob, saveAttachmentToSystem } from '../handlers/chat';
import type { PendingAttachment } from '../lib/attachments';
import type { AttachmentOut } from '../lib/types';
import { useChatUi, type PreviewTarget } from '../components/chatContext';

/** The bytes of a sent attachment: inline when the message carries them, else fetched. */
export function attachmentLoader(conversationId: string | null, messageId: string, a: AttachmentOut) {
  return async (): Promise<Blob> => {
    if (a.data) return blobFromBase64(a.data, a.mime);
    if (!conversationId || !a.blobId) throw new Error('This file is not stored yet.');
    return previewAttachmentBlob(conversationId, messageId, a.blobId);
  };
}

export async function downloadAttachment(conversationId: string | null, messageId: string, a: AttachmentOut) {
  try {
    const blob =
      conversationId && a.blobId
        ? await downloadAttachmentBlob(conversationId, messageId, a.blobId)
        : await attachmentLoader(conversationId, messageId, a)();
    triggerBrowserDownload(blob, downloadName(a.name, a.mime));
  } catch {
    toast.error(`Could not download ${a.name}`);
  }
}

const pendingFile = (p: PendingAttachment): PreviewFile => ({
  id: p.key,
  name: p.name,
  mime: p.mime,
  size: p.size,
  load: async () => p.file,
});

/** A preview target as the shared preview's file. */
export function previewFileOf(target: PreviewTarget, conversationId: string | null): PreviewFile {
  if (target.kind === 'pending') return pendingFile(target.attachment);
  const a = target.attachment;
  return {
    id: a.id,
    name: a.title || a.name,
    mime: a.mime,
    size: a.size,
    meta: a.origin === 'generated' ? ['Generated'] : undefined,
    load: attachmentLoader(conversationId, target.messageId, a),
  };
}

export function useAttachmentActions() {
  const { conversationId, systemId, systemName } = useChatUi();
  const [saving, setSaving] = useState<string | null>(null);

  const save = async (a: AttachmentOut) => {
    if (!systemId) return;
    setSaving(a.id);
    try {
      const res = await saveAttachmentToSystem(systemId, a.id);
      toast.success(
        `Saved to ${systemName ?? systemId}: ${res.file.path}${res.changed ? '' : ' (unchanged)'}`,
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save the file');
    } finally {
      setSaving(null);
    }
  };

  /** Extra actions of a sent file: "Save to <system> folder" in a chat about a system. */
  const extraActions = (a: AttachmentOut): FileAction[] =>
    systemId
      ? [
          {
            label: `Save to ${systemName ?? systemId} folder`,
            icon: <FolderInput />,
            onSelect: () => void save(a),
            disabled: saving === a.id,
          },
        ]
      : [];

  return {
    conversationId,
    extraActions,
    download: (messageId: string, a: AttachmentOut) => downloadAttachment(conversationId, messageId, a),
  };
}
