/**
 * Composer attachments (port of magenticx `shared/lib/uploadGuards.ts` + the attachment
 * preview registry). Files go to the backend as base64 inside the message JSON, so the limits
 * here mirror `core/settings.py` (`ATTACHMENT_*`): 25 MB per file, 25 MB per message, 10 files.
 */
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

export type PreviewKind =
  | 'image'
  | 'pdf'
  | 'docx'
  | 'markdown'
  | 'csv'
  | 'json'
  | 'code'
  | 'text'
  | 'unsupported';

const ext = (name: string) => /\.([^.]+)$/.exec(name.trim().toLowerCase())?.[1] ?? '';

const CODE_EXT: Record<string, string> = {
  py: 'python',
  ts: 'typescript',
  tsx: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  sql: 'sql',
  sh: 'bash',
  yaml: 'yaml',
  yml: 'yaml',
  xml: 'xml',
  html: 'xml',
  css: 'css',
  go: 'go',
  java: 'java',
  rs: 'rust',
};

/** Guess a MIME type the backend accepts when the browser leaves it empty. */
export function mimeOf(file: { name: string; type?: string }): string {
  if (file.type) return file.type.toLowerCase();
  const e = ext(file.name);
  if (e === 'md' || e === 'markdown') return 'text/markdown';
  if (e === 'csv') return 'text/csv';
  if (e === 'json') return 'application/json';
  if (e === 'yaml' || e === 'yml') return 'application/yaml';
  if (e === 'docx') return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
  if (e === 'pdf') return 'application/pdf';
  if (CODE_EXT[e] || e === 'txt' || e === 'log') return 'text/plain';
  return 'application/octet-stream';
}

export function previewKind(meta: { name: string; mime: string }): PreviewKind {
  const mime = meta.mime.toLowerCase();
  const e = ext(meta.name);
  if (mime.startsWith('image/')) return 'image';
  if (mime === 'application/pdf' || e === 'pdf') return 'pdf';
  if (e === 'docx' || mime.includes('wordprocessingml')) return 'docx';
  if (e === 'md' || e === 'markdown' || mime === 'text/markdown') return 'markdown';
  if (e === 'csv' || mime === 'text/csv') return 'csv';
  if (e === 'json' || mime === 'application/json') return 'json';
  if (CODE_EXT[e]) return 'code';
  if (mime.startsWith('text/') || ['txt', 'log'].includes(e)) return 'text';
  return 'unsupported';
}

export const codeLanguage = (name: string) => CODE_EXT[ext(name)];

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

export function formatBytes(n: number | null | undefined): string {
  if (!n && n !== 0) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** Inline image source for an attachment that carries its bytes. */
export function imageSrc(a: Pick<AttachmentOut, 'mime' | 'data'>): string | null {
  return a.data ? `data:${a.mime};base64,${a.data}` : null;
}
