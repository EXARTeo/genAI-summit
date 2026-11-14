/**
 * File helpers shared by every surface that shows a file (chat attachments, system folders, audit
 * artifacts). Port of magenticx `features/attachments/components/attachment_preview_parts/registry.ts`
 * + `shared/lib/uploadGuards.ts`: what kind a file is (by MIME type, then extension), whether the
 * browser can preview it, its type label, a CSV reader and base64 / download helpers. Pure, no React.
 */

export type FileKind =
  | 'image'
  | 'pdf'
  | 'docx'
  | 'markdown'
  | 'csv'
  | 'json'
  | 'code'
  | 'text'
  | 'unsupported';

/** What the preview needs to know about a file. */
export interface FileMeta {
  name: string;
  mime?: string | null;
  size?: number | null;
}

export interface FileDescriptor {
  kind: FileKind;
  /** Whether the preview panel can render it (images open in the lightbox). */
  previewable: boolean;
  /** Human label: "PDF", "Word document", "Markdown", "CSV", "YAML"… */
  label: string;
  /** highlight.js language for code and JSON. */
  language?: string;
  /** Why it cannot be previewed (shown with the download fallback). */
  reason?: string;
}

/** Text kinds are read into memory; above this they are not previewed. */
export const TEXT_PREVIEW_LIMIT_BYTES = 5 * 1024 * 1024;
export const OFFICE_PREVIEW_LIMIT_BYTES = 25 * 1024 * 1024;

export function fileExtension(name: string): string {
  return /\.([^./\\]+)$/.exec(name.trim().toLowerCase())?.[1] ?? '';
}

/** The last path segment ("plugins/x/plugin.yaml" → "plugin.yaml"). */
export function baseName(path: string): string {
  return path.split(/[/\\]/).filter(Boolean).pop() ?? path;
}

const CODE_LANGUAGES: Record<string, string> = {
  c: 'c',
  cc: 'cpp',
  cpp: 'cpp',
  cs: 'csharp',
  css: 'css',
  go: 'go',
  h: 'cpp',
  html: 'xml',
  java: 'java',
  js: 'javascript',
  jsx: 'javascript',
  kt: 'kotlin',
  php: 'php',
  py: 'python',
  rb: 'ruby',
  rs: 'rust',
  scss: 'scss',
  sh: 'bash',
  sql: 'sql',
  toml: 'ini',
  ts: 'typescript',
  tsx: 'typescript',
  xml: 'xml',
  yaml: 'yaml',
  yml: 'yaml',
};

const LANGUAGE_LABELS: Record<string, string> = { yaml: 'YAML', python: 'Python', sql: 'SQL', xml: 'XML' };

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'avif']);
const MARKDOWN_EXTENSIONS = new Set(['md', 'markdown', 'mdx']);
const TEXT_EXTENSIONS = new Set(['txt', 'text', 'log']);

/** The highlight.js language for a file name, if it is code. */
export const codeLanguage = (name: string): string | undefined => CODE_LANGUAGES[fileExtension(name)];

/**
 * A MIME type for a file the browser left untyped (pasted files, `.md`, `.yaml`), so the backend
 * and the preview see the same kind.
 */
export function guessMime(file: { name: string; type?: string | null }): string {
  if (file.type) return file.type.toLowerCase();
  const e = fileExtension(file.name);
  if (MARKDOWN_EXTENSIONS.has(e)) return 'text/markdown';
  if (e === 'csv') return 'text/csv';
  if (e === 'json') return 'application/json';
  if (e === 'yaml' || e === 'yml') return 'application/yaml';
  if (e === 'docx') return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
  if (e === 'pdf') return 'application/pdf';
  if (e === 'jpg' || e === 'jpeg') return 'image/jpeg';
  if (IMAGE_EXTENSIONS.has(e)) return `image/${e}`;
  if (CODE_LANGUAGES[e] || TEXT_EXTENSIONS.has(e)) return 'text/plain';
  return 'application/octet-stream';
}

function tooLarge(meta: FileMeta, limit: number, label: string): FileDescriptor | null {
  if (typeof meta.size !== 'number' || meta.size <= limit) return null;
  return {
    kind: 'unsupported',
    previewable: false,
    label,
    reason: `Preview is turned off for files larger than ${Math.round(limit / 1024 / 1024)} MB.`,
  };
}

/** What a file is and whether the browser can preview it (MIME type first, then extension). */
export function classifyFile(meta: FileMeta): FileDescriptor {
  const mime = (meta.mime ?? '').trim().toLowerCase();
  const e = fileExtension(meta.name);

  if (mime.startsWith('image/') || IMAGE_EXTENSIONS.has(e) || e === 'svg') {
    if (mime === 'image/svg+xml' || e === 'svg')
      return {
        kind: 'unsupported',
        previewable: false,
        label: 'SVG image',
        reason: 'SVG files are not previewed (they can carry scripts). Download it to open it.',
      };
    return { kind: 'image', previewable: true, label: 'Image' };
  }
  if (mime === 'application/pdf' || e === 'pdf') return { kind: 'pdf', previewable: true, label: 'PDF' };
  if (mime.includes('wordprocessingml') || e === 'docx')
    return (
      tooLarge(meta, OFFICE_PREVIEW_LIMIT_BYTES, 'Word document') ?? {
        kind: 'docx',
        previewable: true,
        label: 'Word document',
      }
    );
  if (['doc', 'xls', 'xlsx', 'ppt', 'pptx'].includes(e) || mime.includes('officedocument'))
    return {
      kind: 'unsupported',
      previewable: false,
      label: 'Office file',
      reason: 'This Office format cannot be previewed in the browser. Download it to open it.',
    };
  if (mime === 'text/csv' || e === 'csv')
    return (
      tooLarge(meta, TEXT_PREVIEW_LIMIT_BYTES, 'CSV') ?? { kind: 'csv', previewable: true, label: 'CSV' }
    );
  if (mime === 'application/json' || e === 'json')
    return (
      tooLarge(meta, TEXT_PREVIEW_LIMIT_BYTES, 'JSON') ?? {
        kind: 'json',
        previewable: true,
        label: 'JSON',
        language: 'json',
      }
    );
  if (MARKDOWN_EXTENSIONS.has(e) || mime === 'text/markdown')
    return (
      tooLarge(meta, TEXT_PREVIEW_LIMIT_BYTES, 'Markdown') ?? {
        kind: 'markdown',
        previewable: true,
        label: 'Markdown',
        language: 'markdown',
      }
    );
  const language = CODE_LANGUAGES[e] ?? (mime.includes('yaml') ? 'yaml' : undefined);
  if (language) {
    const label = LANGUAGE_LABELS[language] ?? 'Code';
    return (
      tooLarge(meta, TEXT_PREVIEW_LIMIT_BYTES, label) ?? { kind: 'code', previewable: true, label, language }
    );
  }
  if (mime.startsWith('text/') || TEXT_EXTENSIONS.has(e))
    return (
      tooLarge(meta, TEXT_PREVIEW_LIMIT_BYTES, 'Text') ?? { kind: 'text', previewable: true, label: 'Text' }
    );
  return {
    kind: 'unsupported',
    previewable: false,
    label: 'File',
    reason: 'There is no preview for this file type. Download it to open it.',
  };
}

export const isImageFile = (meta: FileMeta): boolean => classifyFile(meta).kind === 'image';

/** Text kinds the preview reads into memory. */
export const isTextKind = (kind: FileKind): boolean =>
  kind === 'markdown' || kind === 'csv' || kind === 'json' || kind === 'code' || kind === 'text';

/** "1.2 MB", "" when the size is unknown. */
export function formatFileSize(size: number | null | undefined): string {
  if (typeof size !== 'number' || Number.isNaN(size) || size < 0) return '';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(size < 10 * 1024 ? 1 : 0)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

/** "PDF · 1.2 MB": the chip and preview subtitle. */
export function fileSubtitle(meta: FileMeta, extra?: (string | null | undefined)[]): string {
  const { label } = classifyFile(meta);
  return [...(extra ?? []), label === 'File' && meta.mime ? meta.mime : label, formatFileSize(meta.size)]
    .filter(Boolean)
    .join(' · ');
}

/**
 * CSV rows (RFC 4180: quoted fields with commas, "" escapes and line breaks), at most `limit`
 * rows. Enough for a preview, not a full parser (no delimiter sniffing).
 */
export function parseCsv(text: string, limit = 500): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  const src = text.replace(/^\uFEFF/, '');
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"' && src[i + 1] === '"') {
        cell += '"';
        i += 1;
      } else if (ch === '"') quoted = false;
      else cell += ch;
      continue;
    }
    if (ch === '"') quoted = true;
    else if (ch === ',') {
      row.push(cell);
      cell = '';
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && src[i + 1] === '\n') i += 1;
      row.push(cell);
      cell = '';
      if (row.some((c) => c !== '')) rows.push(row);
      row = [];
      if (rows.length >= limit) return rows;
    } else cell += ch;
  }
  row.push(cell);
  if (row.some((c) => c !== '')) rows.push(row);
  return rows.slice(0, limit);
}

/** Bytes from base64 (no `data:` prefix) as a Blob. */
export function blobFromBase64(b64: string, mime = 'application/octet-stream'): Blob {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

const EXTENSION_BY_MIME: Record<string, string> = {
  'image/jpeg': 'jpg',
  'image/png': 'png',
  'image/gif': 'gif',
  'image/webp': 'webp',
  'application/pdf': 'pdf',
};

/** A download name with an extension (an extensionless file is one the OS cannot open). */
export function downloadName(name: string | undefined, mime?: string | null): string {
  const ext = EXTENSION_BY_MIME[(mime ?? '').toLowerCase()];
  const given = (name ?? '').trim() || 'file';
  if (fileExtension(given) || !ext) return given;
  return `${given}.${ext}`;
}

/** Save a Blob as a file through a temporary object URL (the browser's download, no server). */
export function triggerBrowserDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  link.rel = 'noopener';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
