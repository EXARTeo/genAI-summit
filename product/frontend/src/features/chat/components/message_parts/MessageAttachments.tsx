/**
 * A message's files (magenticx `message_parts/MessageAttachments.tsx`): image thumbnails and file
 * tiles that open the preview; each has download and, in a chat about a system, "Save to
 * <system> folder" (`POST /v1/systems/{id}/files/from-attachment`).
 */
import {
  Download,
  FileCode2,
  FileImage,
  FileSpreadsheet,
  FileText,
  FolderInput,
  MoreHorizontal,
  Sparkles,
} from 'lucide-react';
import { useState } from 'react';
import { cn } from '@/shared/lib/utils';
import { DropdownMenu, IconButton, toast } from '@/shared/ui';
import { downloadAttachmentBlob, saveAttachmentToSystem } from '../../handlers/chat';
import { formatBytes, imageSrc, previewKind } from '../../lib/attachments';
import type { AttachmentOut } from '../../lib/types';
import { useChatUi } from '../chatContext';

export function fileIconFor(meta: { name: string; mime: string }) {
  const kind = previewKind(meta);
  if (kind === 'image') return FileImage;
  if (kind === 'csv') return FileSpreadsheet;
  if (kind === 'code' || kind === 'json') return FileCode2;
  return FileText;
}

export async function downloadAttachment(conversationId: string, messageId: string, a: AttachmentOut) {
  if (!a.blobId) return;
  try {
    const blob = await downloadAttachmentBlob(conversationId, messageId, a.blobId);
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = a.name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch {
    toast.error(`Could not download ${a.name}`);
  }
}

function useSaveToSystem() {
  const { systemId, systemName } = useChatUi();
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
  return { systemId, systemName, save, saving };
}

export function MessageAttachments({
  attachments,
  messageId,
  align = 'start',
}: {
  attachments: AttachmentOut[];
  messageId: string;
  align?: 'start' | 'end';
}) {
  const { conversationId, openPreview } = useChatUi();
  const { systemId, systemName, save, saving } = useSaveToSystem();
  if (!attachments.length) return null;
  const images = attachments.filter((a) => imageSrc(a));
  const files = attachments.filter((a) => !imageSrc(a));

  const menu = (a: AttachmentOut) => (
    <DropdownMenu
      trigger={
        <IconButton label="File actions" size="icon-sm" icon={<MoreHorizontal />} className="shrink-0" />
      }
      items={[
        {
          label: 'Preview',
          icon: <FileText />,
          onSelect: () => openPreview({ kind: 'sent', attachment: a, messageId }),
        },
        {
          label: 'Download',
          icon: <Download />,
          disabled: !conversationId || !a.blobId,
          onSelect: () => conversationId && void downloadAttachment(conversationId, messageId, a),
        },
        ...(systemId
          ? [
              { type: 'separator' as const },
              {
                label: `Save to ${systemName ?? systemId} folder`,
                icon: <FolderInput />,
                disabled: saving === a.id,
                onSelect: () => void save(a),
              },
            ]
          : []),
      ]}
    />
  );

  return (
    <div className={cn('flex flex-col gap-2', align === 'end' ? 'items-end' : 'items-start')}>
      {images.length > 0 && (
        <div className={cn('flex flex-wrap gap-2', align === 'end' && 'justify-end')}>
          {images.map((a) => (
            <button
              key={a.id}
              type="button"
              onClick={() => openPreview({ kind: 'sent', attachment: a, messageId })}
              className="overflow-hidden rounded-lg border border-border bg-surface-muted transition-colors hover:border-primary/40"
              aria-label={`Preview ${a.name}`}
            >
              <img
                src={imageSrc(a) ?? ''}
                alt={a.name}
                className="size-24 object-cover [image-rendering:auto]"
              />
            </button>
          ))}
        </div>
      )}
      {files.length > 0 && (
        <div className={cn('flex flex-wrap gap-2', align === 'end' && 'justify-end')}>
          {files.map((a) => {
            const Icon = a.origin === 'generated' ? Sparkles : fileIconFor(a);
            return (
              <div
                key={a.id}
                className="group flex w-60 items-center gap-2.5 rounded-lg border border-border bg-surface py-1.5 pl-2 pr-1 transition-colors hover:border-primary/40"
              >
                <button
                  type="button"
                  onClick={() => openPreview({ kind: 'sent', attachment: a, messageId })}
                  className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
                >
                  <span className="grid size-8 shrink-0 place-items-center rounded-md bg-surface-muted text-muted">
                    <Icon className="size-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-xs font-medium">{a.title ?? a.name}</span>
                    <span className="block truncate text-2xs text-muted">
                      {a.origin === 'generated' ? 'Generated · ' : ''}
                      {formatBytes(a.size)}
                    </span>
                  </span>
                </button>
                {menu(a)}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
