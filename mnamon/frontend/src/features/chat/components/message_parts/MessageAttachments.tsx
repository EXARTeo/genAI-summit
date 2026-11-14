/**
 * A message's files (magenticx `message_parts/MessageAttachments.tsx`) on the shared pieces: file
 * chips (`FileChip`, a 40 px accent tile, the name and type · size; Preview / Download on hover) above
 * the image grid (`ImageGrid`, which opens the shared lightbox and steps through the message's
 * images). Like magenticx a file that cannot be previewed downloads on click. Mnamon adds a ⋯ menu
 * with "Save to <system> folder" in a chat about a system.
 */
import { Download, Sparkles } from 'lucide-react';
import { classifyFile, fileSubtitle } from '@/shared/lib/files';
import { cn } from '@/shared/lib/utils';
import { FileChip, ImageGrid } from '@/shared/ui';
import { useAttachmentActions } from '../../hooks/useAttachmentActions';
import { imageSrc } from '../../lib/attachments';
import type { AttachmentOut } from '../../lib/types';
import { useChatUi } from '../chatContext';

export function MessageAttachments({
  attachments,
  messageId,
  align = 'start',
}: {
  attachments: AttachmentOut[];
  messageId: string;
  align?: 'start' | 'end';
}) {
  const { openPreview } = useChatUi();
  const { extraActions, download } = useAttachmentActions();
  if (!attachments.length) return null;
  const images = attachments.filter((a) => imageSrc(a));
  const files = attachments.filter((a) => !imageSrc(a));
  const end = align === 'end';

  return (
    <div
      className={cn('flex max-w-[85%] flex-col gap-3', end ? 'items-end self-end' : 'items-start')}
      data-testid="message-attachments"
    >
      {files.length > 0 && (
        <div className={cn('flex flex-col gap-2', end ? 'items-end' : 'items-start')}>
          {files.map((a) => {
            const generated = a.origin === 'generated';
            const previewable = classifyFile(a).previewable;
            return (
              <FileChip
                key={a.id}
                variant="message"
                name={a.name}
                title={a.title}
                mime={a.mime}
                size={a.size}
                icon={generated ? Sparkles : undefined}
                subtitle={generated ? fileSubtitle(a, ['Generated']) : undefined}
                onOpen={
                  previewable ? () => openPreview({ kind: 'sent', attachment: a, messageId }) : undefined
                }
                onDownload={() => void download(messageId, a)}
                actions={extraActions(a)}
              />
            );
          })}
        </div>
      )}
      {images.length > 0 && (
        <ImageGrid
          align={align}
          images={images.map((a) => ({
            id: a.id,
            src: imageSrc(a) ?? '',
            name: a.title || a.name,
            mime: a.mime,
            actions: [
              { label: 'Download', icon: <Download />, onSelect: () => void download(messageId, a) },
              ...extraActions(a),
            ],
          }))}
          onDownload={(_img, i) => void download(messageId, images[i])}
        />
      )}
    </div>
  );
}
