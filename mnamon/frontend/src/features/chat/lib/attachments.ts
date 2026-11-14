/**
 * Composer attachments (port of magenticx `shared/lib/uploadGuards.ts`; kinds, sizes and the
 * preview registry are shared in `@/shared/lib/files`). Files go to the backend as base64 inside the message JSON, so the limits
 * here mirror `core/settings.py` (`ATTACHMENT_*`): 25 MB per file, 25 MB per message, 10 files.
 */
import { classifyFile, guessMime, type FileKind, type FileMeta } from '@/shared/lib/files';
import type { AttachmentIn, AttachmentOut } from './types';

export const MAX_FILE_BYTES = 25 * 1024 * 1024;
export const MAX_TOTAL_BYTES = 25 * 1024 * 1024;
export const MAX_FILES = 10;

/** A file in the composer, before it is sent. `progress` is the read progress (0..1). */
export interface PendingAttachment {
  key: string;
  file: File;
  name: string;
  mime: string;
  size: number;
  progress: number;
  dataB64?: string;
  error?: string;
}

/** A MIME type the backend accepts when the browser leaves it empty (shared `guessMime`). */
export const mimeOf = guessMime;

/** The preview kind of a file (shared `classifyFile`). */
export const previewKind = (meta: FileMeta): FileKind => classifyFile(meta).kind;

/** Why these files cannot be added to `existing`, or null when they can. */
export function checkFiles(files: File[], existing: { size: number }[]): string | null {
  if (existing.length + files.length > MAX_FILES) return `At most ${MAX_FILES} files per message.`;
  const big = files.find((f) => f.size > MAX_FILE_BYTES);
  if (big) return `${big.name} is larger than ${MAX_FILE_BYTES / 1024 / 1024} MB.`;
  const empty = files.find((f) => f.size === 0);
  if (empty) return `${empty.name} is empty.`;
  const total = [...existing, ...files].reduce((n, f) => n + f.size, 0);
  if (total > MAX_TOTAL_BYTES)
    return `Attachments are limited to ${MAX_TOTAL_BYTES / 1024 / 1024} MB per message.`;
  return null;
}

/** Read a file as base64 (no data: prefix), reporting progress. */
export function readAsBase64(file: File, onProgress?: (p: number) => void): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    reader.onerror = () => reject(reader.error ?? new Error('Could not read the file'));
    reader.onload = () => {
      const result = String(reader.result ?? '');
      onProgress?.(1);
      resolve(result.slice(result.indexOf(',') + 1));
    };
    reader.readAsDataURL(file);
  });
}

export function toAttachmentIn(p: PendingAttachment): AttachmentIn {
  return { name: p.name, mime: p.mime, dataB64: p.dataB64 ?? '', size: p.size };
}

/** Inline image source for an attachment that carries its bytes. */
export function imageSrc(a: Pick<AttachmentOut, 'mime' | 'data'>): string | null {
  return a.data ? `data:${a.mime};base64,${a.data}` : null;
}
