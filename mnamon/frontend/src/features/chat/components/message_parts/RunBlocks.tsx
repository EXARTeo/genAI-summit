/**
 * Smaller run blocks (magenticx `ArtifactCard`, `TaskRefBlockView`, `TaskSettledMarker` /
 * `ConversationMarkers.TaskMarker`): a presented artifact (opens the
 * generated attachment it maps to in the shared preview, with Preview / Download on hover; a
 * presented image shows as the image itself and opens the shared lightbox), a background task started
 * or settled (the plan moved to the composer's plan panel, `plan_parts/`). magenticx's gradient tile and card
 * fill are flat token surfaces here (no decorative gradients).
 */
import { motion } from 'framer-motion';
import {
  Bot,
  Check,
  CircleAlert,
  CornerDownRight,
  Download,
  Eye,
  FileText,
  Loader2,
  Sparkles,
} from 'lucide-react';
import { useState } from 'react';
import { classifyFile } from '@/shared/lib/files';
import { cn } from '@/shared/lib/utils';
import { listItem } from '@/shared/lib/motion';
import { ImageLightbox } from '@/shared/ui';
import { useAttachmentActions } from '../../hooks/useAttachmentActions';
import { imageSrc } from '../../lib/attachments';
import { toTitleCase } from '../../lib/hitl';
import type { ArtifactBlock, TaskRefBlock, TaskSettledBlock } from '../../lib/timeline';
import type { AttachmentOut } from '../../lib/types';
import { useChatUi } from '../chatContext';

const ROUND_ACTION =
  'grid size-7 place-items-center rounded-full border border-border/50 bg-background/90 text-text shadow-sm transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

export function ArtifactCard({
  block,
  attachment,
  messageId,
}: {
  block: ArtifactBlock;
  attachment?: AttachmentOut;
  messageId: string;
}) {
  const { openPreview } = useChatUi();
  const { download } = useAttachmentActions();
  const [expanded, setExpanded] = useState(false);
  const ready = Boolean(attachment);
  const primary = block.title ?? block.filename;
  const secondary = block.summary || block.path;
  const canPreview = Boolean(attachment) && classifyFile(attachment!).previewable;
  const preview = () => attachment && openPreview({ kind: 'sent', attachment, messageId });
  const save = () => attachment && void download(messageId, attachment);
  // Tapping the card previews when the file can be previewed, else downloads (magenticx).
  const activate = () => (canPreview ? preview() : save());

  // A presented image is shown as the image itself (magenticx), opening the shared lightbox.
  const image = attachment ? imageSrc(attachment) : null;
  if (attachment && image) {
    return (
      <motion.figure variants={listItem} initial="initial" animate="animate" className="w-fit max-w-full">
        <div className="group/artifact relative w-fit max-w-full">
          <button
            type="button"
            onClick={() => setExpanded(true)}
            aria-label={`View ${primary} larger`}
            className="block cursor-zoom-in rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          >
            <img
              src={image}
              alt={block.summary || primary}
              className="block max-h-[28rem] w-auto max-w-full rounded-2xl border border-border/50 bg-surface-sunken/40 object-contain shadow-sm transition-transform duration-200 group-hover/artifact:scale-[1.01] motion-reduce:transition-none sm:max-w-md"
            />
          </button>
          <button
            type="button"
            aria-label={`Download ${primary}`}
            onClick={save}
            className={cn(
              ROUND_ACTION,
              'absolute right-2.5 top-2.5 size-8 opacity-0 focus-visible:opacity-100 group-hover/artifact:opacity-100 [@media(hover:none)]:opacity-100',
            )}
          >
            <Download className="size-3.5" />
          </button>
        </div>
        <figcaption className="mt-1.5 flex items-center gap-1.5 px-1 text-xs text-muted">
          <Sparkles className="size-[11px] shrink-0 text-primary/70" aria-hidden />
          <span className="truncate">{primary}</span>
        </figcaption>
        <ImageLightbox
          images={[
            { src: image, name: block.filename, alt: block.summary || primary, mime: attachment.mime },
          ]}
          index={expanded ? 0 : null}
          onClose={() => setExpanded(false)}
          onDownload={save}
        />
      </motion.figure>
    );
  }

  return (
    <motion.div variants={listItem} initial="initial" animate="animate" className="w-full max-w-sm">
      <div
        role={ready ? 'button' : undefined}
        tabIndex={ready ? 0 : undefined}
        aria-label={ready ? `Open ${primary}` : undefined}
        onClick={ready ? activate : undefined}
        onKeyDown={
          ready
            ? (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  activate();
                }
              }
            : undefined
        }
        className={cn(
          'group/artifact relative overflow-hidden rounded-2xl border border-border/60 bg-surface-sunken/40 p-3.5 transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          ready && 'cursor-pointer hover:border-primary/40 hover:bg-surface-sunken/70',
        )}
      >
        <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-primary/80">
          <Sparkles className="size-[11px]" aria-hidden />
          Generated document
        </div>
        <div className="flex items-start gap-3">
          <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-primary text-primary-foreground shadow-sm">
            <FileText className="size-[18px]" />
          </span>
          <div className="min-w-0 flex-1 pr-1">
            <div className="truncate text-sm font-semibold text-text">{primary}</div>
            <div className="mt-0.5 line-clamp-2 text-xs leading-snug text-muted">{secondary}</div>
            {!ready && (
              <div className="mt-2 flex items-center gap-1.5 text-2xs text-muted">
                <Loader2 className="size-3 animate-spin" aria-hidden />
                Preparing…
              </div>
            )}
          </div>
        </div>
        {ready && (
          <div className="pointer-events-none absolute right-2.5 top-2.5 flex items-center gap-1 opacity-0 transition-opacity duration-200 group-focus-within/artifact:pointer-events-auto group-focus-within/artifact:opacity-100 group-hover/artifact:pointer-events-auto group-hover/artifact:opacity-100">
            {canPreview && (
              <button
                type="button"
                aria-label={`Preview ${primary}`}
                className={ROUND_ACTION}
                onClick={(e) => {
                  e.stopPropagation();
                  preview();
                }}
              >
                <Eye className="size-3.5" />
              </button>
            )}
            <button
              type="button"
              aria-label={`Download ${primary}`}
              className={ROUND_ACTION}
              onClick={(e) => {
                e.stopPropagation();
                save();
              }}
            >
              <Download className="size-3.5" />
            </button>
          </div>
        )}
      </div>
    </motion.div>
  );
}

/** "↳ Started task in the background" over the task's card row. */
export function TaskRefRow({ block }: { block: TaskRefBlock }) {
  const title = toTitleCase(block.name) ?? block.name;
  return (
    <div className="space-y-1.5">
      <p className="flex items-center gap-1.5 px-1 text-xs text-muted">
        <CornerDownRight className="size-3.5 shrink-0" aria-hidden />
        <span className="min-w-0 truncate">
          {block.action === 'update' ? 'Updated task in the background' : 'Started task in the background'}
        </span>
      </p>
      <div className="flex min-w-0 items-center gap-2.5 rounded-[22px] border border-border/70 bg-surface px-3.5 py-2.5 shadow-card">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-primary/10 text-primary">
          <Bot className="size-4" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13.5px] font-semibold text-text">{title}</span>
          {block.description && (
            <span className="block truncate text-xs leading-[1.15rem] text-muted">{block.description}</span>
          )}
        </span>
      </div>
    </div>
  );
}

/** A background task's result arrived: its outcome on a rule. */
export function TaskSettledRow({ block }: { block: TaskSettledBlock }) {
  const ok = block.status === 'success' || block.status === 'completed';
  const name = toTitleCase(block.name) ?? block.name;
  const text = ok ? `${name} finished` : `${name} ${block.status}`;
  return (
    <div role="separator" aria-label={text} className="flex w-full items-center gap-3 py-0.5 text-xs">
      <span aria-hidden className="h-px flex-1 bg-border" />
      <span
        className={cn('flex shrink-0 items-center gap-1.5 font-medium', ok ? 'text-success' : 'text-danger')}
      >
        {ok ? <Check className="size-3.5" /> : <CircleAlert className="size-3.5" />}
        {text}
      </span>
      <span aria-hidden className="h-px flex-1 bg-border" />
    </div>
  );
}
