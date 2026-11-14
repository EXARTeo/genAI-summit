/**
 * A message's files (magenticx `message_parts/MessageAttachments.tsx`): file chips (a 40 px
 * accent tile, the name and the type) above image thumbnails, all opening the preview. Each keeps
 * our ⋯ menu instead of magenticx's hover buttons: Preview, Download and, in a chat about a
 * system, "Save to <system> folder" (`POST /v1/systems/{id}/files/from-attachment`).
 */
import {
  Download,
  Eye,
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
import { triggerBrowserDownload } from '../../lib/download';
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
    triggerBrowserDownload(blob, a.name);
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

/** The ⋯ trigger: shown on hover / focus with a pointer, always on touch screens. */
const MENU_TRIGGER =
  'size-7 shrink-0 text-muted hover:bg-hover hover:text-text data-[state=open]:opacity-100 opacity-0 group-hover/file:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100';

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
  const end = align === 'end';
  const preview = (a: AttachmentOut) => openPreview({ kind: 'sent', attachment: a, messageId });

  const menu = (a: AttachmentOut, className?: string) => (
    <DropdownMenu
      trigger={<IconButton label={`Actions for ${a.name}`} icon={<MoreHorizontal />} className={className} />}
      items={[
        { label: 'Preview', icon: <Eye />, onSelect: () => preview(a) },
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
    <div
      className={cn('flex max-w-[85%] flex-col gap-3', end ? 'items-end self-end' : 'items-start')}
      data-testid="message-attachments"
    >
      {files.length > 0 && (
        <div className={cn('flex flex-col gap-2', end ? 'items-end' : 'items-start')}>
          {files.map((a) => {
            const generated = a.origin === 'generated';
            const Icon = generated ? Sparkles : fileIconFor(a);
            const meta = [generated ? 'Generated' : null, a.mime || 'File', formatBytes(a.size)]
              .filter(Boolean)
              .join(' · ');
            return (
              <div
                key={a.id}
                className="group/file flex w-64 items-center gap-1 rounded-2xl border border-border/50 bg-surface-sunken/30 py-2.5 pl-3 pr-1.5 text-xs transition-colors hover:bg-surface-sunken/60 md:w-80"
              >
                <button
                  type="button"
                  onClick={() => preview(a)}
                  className="flex min-w-0 flex-1 items-center gap-3 rounded-xl text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                  aria-label={`Preview ${a.name}`}
                >
                  <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary/90 text-primary-foreground">
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-text/90">{a.title ?? a.name}</span>
                    <span className="block truncate text-muted/80">{meta}</span>
                  </span>
                </button>
                {menu(a, MENU_TRIGGER)}
              </div>
            );
          })}
        </div>
      )}
      {images.length > 0 && (
        <div className={cn('grid grid-cols-2 gap-3', end && 'justify-items-end')}>
          {images.map((a, i) => (
            <div
              key={a.id}
              className={cn(
                'group/file relative',
                images.length % 2 === 1 && i === images.length - 1 && images.length > 1 && 'col-span-2',
                images.length === 1 && 'col-span-2',
              )}
            >
              <button
                type="button"
                onClick={() => preview(a)}
                className="group/img relative block overflow-hidden rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                aria-label={`Preview ${a.name}`}
              >
                <img
                  src={imageSrc(a) ?? ''}
                  alt={a.name}
                  className="h-28 w-40 object-cover transition-transform duration-200 group-hover/img:scale-[1.02] md:h-32 md:w-48"
                />
                <span className="absolute inset-0 grid place-items-center opacity-0 transition-opacity group-hover/img:opacity-100 group-focus-visible/img:opacity-100">
                  <span className="grid size-8 place-items-center rounded-full border border-border/50 bg-background/95 text-text shadow-pop">
                    <Eye className="size-4" aria-hidden />
                  </span>
                </span>
              </button>
              <div className="absolute right-1 top-1">
                {menu(a, cn(MENU_TRIGGER, 'bg-background/90 hover:bg-background'))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
