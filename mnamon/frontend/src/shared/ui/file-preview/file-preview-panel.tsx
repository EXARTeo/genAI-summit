/**
 * The file preview (magenticx `features/attachments/AttachmentPreviewPanel.tsx`): a large centred
 * panel (full screen on a phone) with the file's name, "type · MIME · size", Download, extra actions
 * and Close, over a body that renders the file by kind: PDF, DOCX, Markdown, CSV (table), JSON /
 * code (highlighted), text, image, else "no preview" with a download fallback.
 *
 * Data in, callbacks out: the caller hands a `PreviewFile` whose `load()` returns the bytes (a chat
 * attachment, a system folder file, a composer file); nothing here knows the API. Radix Dialog
 * gives focus trap, Escape and focus return; the panel moves with magenticx's panel motion.
 *
 * `FilePreviewBody` is the body alone, for an inline viewer (the system folder tab).
 */
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { AnimatePresence, motion } from 'framer-motion';
import { Download, X } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useFileBlob, useObjectUrl } from '@/shared/hooks/useFileBlob';
import {
  classifyFile,
  downloadName,
  formatFileSize,
  isTextKind,
  triggerBrowserDownload,
  type FileDescriptor,
} from '@/shared/lib/files';
import { panelBackdrop, panelContent } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';
import { Button } from '../button';
import type { FileAction } from '../file-chip';
import { toast } from '../toaster';
import { Tooltip } from '../tooltip';
import {
  CodePreview,
  CsvPreview,
  DocxPreview,
  ImagePreview,
  JsonPreview,
  MarkdownPreview,
  PdfPreview,
  PreviewLoading,
  PreviewMessage,
  TextPreview,
} from './parts';

export interface PreviewFile {
  /** Stable identity of the bytes (blob id, path@version): the load runs once per id. */
  id: string;
  name: string;
  mime?: string | null;
  size?: number | null;
  load: () => Promise<Blob>;
  /** Extra subtitle parts before the type ("v3", "Generated"). */
  meta?: (string | null | undefined)[];
}

/** Text is read up to this many bytes (the rest is cut, with a note). */
const TEXT_READ_LIMIT = 2 * 1024 * 1024;

function errorText(error: unknown): string {
  return error instanceof Error && error.message ? error.message : 'The file could not be loaded.';
}

function Rendered({
  blob,
  file,
  descriptor,
  onDownload,
}: {
  blob: Blob;
  file: PreviewFile;
  descriptor: FileDescriptor;
  onDownload?: () => void;
}) {
  const { kind } = descriptor;
  const forced =
    kind === 'pdf'
      ? 'application/pdf'
      : kind === 'image'
        ? file.mime && file.mime.startsWith('image/') && file.mime !== 'image/svg+xml'
          ? file.mime
          : 'image/png'
        : undefined;
  const url = useObjectUrl(kind === 'pdf' || kind === 'image' ? blob : null, forced);
  const [text, setText] = useState<{ value: string; cut: boolean } | null>(null);
  useEffect(() => {
    if (!isTextKind(kind)) return;
    let cancelled = false;
    const cut = blob.size > TEXT_READ_LIMIT;
    void blob
      .slice(0, TEXT_READ_LIMIT)
      .text()
      .then((value) => !cancelled && setText({ value, cut }));
    return () => {
      cancelled = true;
    };
  }, [blob, kind]);

  if (kind === 'pdf') return url ? <PdfPreview url={url} name={file.name} /> : <PreviewLoading />;
  if (kind === 'image') return url ? <ImagePreview url={url} name={file.name} /> : <PreviewLoading />;
  if (kind === 'docx') return <DocxPreview blob={blob} name={file.name} />;
  if (!isTextKind(kind))
    return (
      <PreviewMessage
        title="No preview"
        description={descriptor.reason ?? 'Download this file to open it in its own application.'}
        onDownload={onDownload}
      />
    );
  if (!text) return <PreviewLoading />;
  const body =
    kind === 'markdown' ? (
      <MarkdownPreview content={text.value} />
    ) : kind === 'csv' ? (
      <CsvPreview content={text.value} />
    ) : kind === 'json' ? (
      <JsonPreview content={text.value} />
    ) : kind === 'code' ? (
      <CodePreview content={text.value} language={descriptor.language} />
    ) : (
      <TextPreview content={text.value} />
    );
  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="min-h-0 flex-1">{body}</div>
      {text.cut && (
        <p className="shrink-0 px-1 text-xs text-muted">
          Showing the first {Math.round(TEXT_READ_LIMIT / 1024 / 1024)} MB. Download the file for the rest.
        </p>
      )}
    </div>
  );
}

export interface FilePreviewBodyProps {
  file: PreviewFile;
  onDownload?: () => void;
  className?: string;
}

/** The preview body alone: loads the bytes and renders them by kind. */
export function FilePreviewBody({ file, onDownload, className }: FilePreviewBodyProps) {
  const descriptor = classifyFile(file);
  const needsBytes = descriptor.previewable;
  const state = useFileBlob(needsBytes ? file.load : null, needsBytes ? file.id : null);
  return (
    <div className={cn('relative h-full min-h-0', className)} data-testid="file-preview-body">
      {!needsBytes ? (
        <PreviewMessage
          title="No preview"
          description={descriptor.reason ?? 'Download this file to open it in its own application.'}
          onDownload={onDownload}
        />
      ) : state.status === 'error' ? (
        <PreviewMessage
          tone="error"
          title="Preview unavailable"
          description={errorText(state.error)}
          onRetry={state.retry}
          onDownload={onDownload}
        />
      ) : state.status === 'ready' ? (
        <Rendered blob={state.blob} file={file} descriptor={descriptor} onDownload={onDownload} />
      ) : (
        <PreviewLoading />
      )}
    </div>
  );
}

/** Load the bytes and save them under the file's name. */
export async function downloadPreviewFile(file: PreviewFile): Promise<void> {
  const blob = await file.load();
  triggerBrowserDownload(blob, downloadName(file.name, file.mime ?? blob.type));
}

export interface FilePreviewPanelProps {
  /** The file shown; null closes. */
  file: PreviewFile | null;
  onClose: () => void;
  /** Overrides the default download (`load()` then save). */
  onDownload?: (file: PreviewFile) => void | Promise<void>;
  /** Hide Download (no bytes to offer). */
  downloadable?: boolean;
  /** Extra header actions ("Save to <system> folder"). */
  actions?: FileAction[];
  /** Extra content under the header (a version picker). */
  toolbar?: ReactNode;
}

export function FilePreviewPanel({
  file,
  onClose,
  onDownload,
  downloadable = true,
  actions,
  toolbar,
}: FilePreviewPanelProps) {
  const open = Boolean(file);
  // Keep the last file while the panel leaves.
  const last = useRef<PreviewFile | null>(null);
  if (file) last.current = file;
  const shown = last.current;
  const [saving, setSaving] = useState(false);

  const download = async () => {
    if (!shown) return;
    setSaving(true);
    try {
      await (onDownload ? onDownload(shown) : downloadPreviewFile(shown));
    } catch (e) {
      toast.error(`Could not download ${shown.name}: ${errorText(e)}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <DialogPrimitive.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <AnimatePresence>
        {open && shown && (
          <DialogPrimitive.Portal forceMount>
            <DialogPrimitive.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-50 bg-scrim-strong"
                variants={panelBackdrop}
                initial="initial"
                animate="animate"
                exit="exit"
              />
            </DialogPrimitive.Overlay>
            <DialogPrimitive.Content
              asChild
              forceMount
              // Escape closes this layer only (not the chat's Esc-to-stop behind it).
              onEscapeKeyDown={(e) => e.stopPropagation()}
            >
              <motion.div
                variants={panelContent}
                initial="initial"
                animate="animate"
                exit="exit"
                data-testid="file-preview"
                className="fixed inset-0 z-50 m-auto flex h-[100dvh] w-screen flex-col overflow-hidden bg-surface text-text shadow-pop outline-none sm:h-[min(94vh,64rem)] sm:w-[min(96vw,76rem)] sm:rounded-2xl sm:border sm:border-border"
              >
                <div className="flex items-center gap-3 border-b border-border px-4 py-3 sm:px-5 sm:py-3.5">
                  <div className="min-w-0 flex-1">
                    <DialogPrimitive.Title className="truncate text-base font-semibold leading-tight">
                      {shown.name}
                    </DialogPrimitive.Title>
                    <DialogPrimitive.Description className="mt-1 truncate text-xs text-muted">
                      {[
                        ...(shown.meta ?? []),
                        classifyFile(shown).label,
                        shown.mime,
                        formatFileSize(shown.size),
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </DialogPrimitive.Description>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {actions?.map((a) => (
                      <Tooltip key={a.label} content={a.label} side="bottom">
                        <Button
                          variant="secondary"
                          leftIcon={a.icon}
                          onClick={a.onSelect}
                          disabled={a.disabled}
                          aria-label={a.label}
                          className="max-sm:w-8 max-sm:px-0"
                        >
                          <span className="hidden max-w-[16rem] truncate sm:inline">{a.label}</span>
                        </Button>
                      </Tooltip>
                    ))}
                    {downloadable && (
                      <Button
                        variant="secondary"
                        leftIcon={<Download />}
                        onClick={() => void download()}
                        loading={saving}
                        aria-label="Download"
                        className="max-sm:w-8 max-sm:px-0"
                      >
                        <span className="hidden sm:inline">Download</span>
                      </Button>
                    )}
                    <DialogPrimitive.Close
                      aria-label="Close preview"
                      className="ml-0.5 grid size-9 place-items-center rounded-full text-muted transition-colors hover:bg-hover hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <X className="size-5" />
                    </DialogPrimitive.Close>
                  </div>
                </div>
                {toolbar}
                <div className="relative min-h-0 flex-1 bg-surface-sunken p-3 sm:p-4">
                  <FilePreviewBody
                    key={shown.id}
                    file={shown}
                    onDownload={downloadable ? () => void download() : undefined}
                  />
                </div>
              </motion.div>
            </DialogPrimitive.Content>
          </DialogPrimitive.Portal>
        )}
      </AnimatePresence>
    </DialogPrimitive.Root>
  );
}
