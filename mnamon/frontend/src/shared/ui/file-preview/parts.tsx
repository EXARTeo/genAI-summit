/**
 * The renderers of the file preview (magenticx `attachment_preview_parts/*`: PreviewChrome,
 * PdfPreview, DocxPreview, TextPreviews), on our tokens. Each text view sits in a frame with a
 * header row (the type, a Copy button) like magenticx; PDF goes through the browser viewer, DOCX
 * is converted in the browser (mammoth, lazy-loaded) into a script-less sandboxed frame.
 */
import { useQuery } from '@tanstack/react-query';
import hljs from 'highlight.js/lib/core';
import bash from 'highlight.js/lib/languages/bash';
import css from 'highlight.js/lib/languages/css';
import go from 'highlight.js/lib/languages/go';
import ini from 'highlight.js/lib/languages/ini';
import java from 'highlight.js/lib/languages/java';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import markdown from 'highlight.js/lib/languages/markdown';
import python from 'highlight.js/lib/languages/python';
import rust from 'highlight.js/lib/languages/rust';
import sql from 'highlight.js/lib/languages/sql';
import typescript from 'highlight.js/lib/languages/typescript';
import xml from 'highlight.js/lib/languages/xml';
import yaml from 'highlight.js/lib/languages/yaml';
import { Check, Copy, Download, FileX2, Loader2, XCircle } from 'lucide-react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { parseCsv } from '@/shared/lib/files';
import { cn } from '@/shared/lib/utils';
import { Button } from '../button';
import { Markdown } from '../markdown';

for (const [name, lang] of Object.entries({
  bash,
  css,
  go,
  ini,
  java,
  javascript,
  json,
  markdown,
  python,
  rust,
  sql,
  typescript,
  xml,
  yaml,
}))
  if (!hljs.getLanguage(name)) hljs.registerLanguage(name, lang);

export function PreviewLoading({ label = 'Opening preview…' }: { label?: string }) {
  return (
    <div className="absolute inset-0 z-10 grid place-items-center bg-surface-sunken/70">
      <div className="flex items-center gap-3 rounded-2xl border border-border bg-surface px-5 py-4 shadow-card">
        <Loader2 className="size-5 animate-spin text-primary" aria-hidden />
        <span className="text-sm text-text">{label}</span>
      </div>
    </div>
  );
}

export function PreviewMessage({
  title,
  description,
  onDownload,
  onRetry,
  tone = 'default',
}: {
  title: string;
  description?: ReactNode;
  onDownload?: () => void;
  onRetry?: () => void;
  tone?: 'default' | 'error';
}) {
  const Icon = tone === 'error' ? XCircle : FileX2;
  return (
    <div className="flex h-full min-h-[16rem] items-center justify-center p-4">
      <div className="max-w-lg rounded-2xl border border-border bg-surface px-6 py-7 text-center shadow-card">
        <div
          className={cn(
            'mx-auto mb-4 grid size-12 place-items-center rounded-2xl',
            tone === 'error' ? 'bg-danger/10 text-danger' : 'bg-surface-sunken text-muted',
          )}
        >
          <Icon className="size-6" aria-hidden />
        </div>
        <h3 className="text-base font-semibold text-text">{title}</h3>
        {description ? <p className="mt-2 text-sm text-muted">{description}</p> : null}
        <div className="mt-5 flex justify-center gap-2">
          {onRetry && (
            <Button variant="secondary" onClick={onRetry}>
              Try again
            </Button>
          )}
          {onDownload && (
            <Button leftIcon={<Download />} onClick={onDownload}>
              Download original file
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

function CopyButton({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 1400);
    return () => window.clearTimeout(t);
  }, [copied]);
  return (
    <Button
      variant="ghost"
      size="sm"
      leftIcon={copied ? <Check /> : <Copy />}
      onClick={() => void navigator.clipboard?.writeText(content).then(() => setCopied(true))}
    >
      {copied ? 'Copied' : 'Copy'}
    </Button>
  );
}

/** A rounded frame with a header row: the type on the left, Copy on the right. */
export function PreviewFrame({
  label,
  copy,
  children,
  className,
  bodyClassName,
}: {
  label: ReactNode;
  copy?: string;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <div
      className={cn(
        'flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-surface',
        className,
      )}
    >
      <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-border pl-3.5 pr-1.5">
        <span className="truncate text-2xs font-medium uppercase tracking-wide text-muted">{label}</span>
        {copy != null && <CopyButton content={copy} />}
      </div>
      <div className={cn('min-h-0 flex-1 overflow-auto', bodyClassName)}>{children}</div>
    </div>
  );
}

export function CodePreview({ content, language }: { content: string; language?: string }) {
  const html = useMemo(() => {
    try {
      if (language && hljs.getLanguage(language))
        return hljs.highlight(content, { language, ignoreIllegals: true }).value;
      return hljs.highlightAuto(content).value;
    } catch {
      return '';
    }
  }, [content, language]);
  return (
    <PreviewFrame label={language || 'text'} copy={content}>
      <pre className="min-w-max p-4 font-mono text-[12.5px] leading-6 text-text">
        {/* highlight.js escapes the source; the output is its own spans only. */}
        {html ? <code dangerouslySetInnerHTML={{ __html: html }} /> : <code>{content}</code>}
      </pre>
    </PreviewFrame>
  );
}

export function TextPreview({ content }: { content: string }) {
  return (
    <PreviewFrame label="text" copy={content}>
      <pre className="whitespace-pre-wrap break-words p-4 font-mono text-[12.5px] leading-6 text-text">
        {content}
      </pre>
    </PreviewFrame>
  );
}

export function JsonPreview({ content }: { content: string }) {
  const pretty = useMemo(() => {
    try {
      return JSON.stringify(JSON.parse(content), null, 2);
    } catch {
      return content;
    }
  }, [content]);
  return <CodePreview content={pretty} language="json" />;
}

export function MarkdownPreview({ content }: { content: string }) {
  return (
    <PreviewFrame label="markdown" copy={content}>
      <div className="mx-auto max-w-3xl px-5 py-6 sm:px-8">
        <Markdown>{content}</Markdown>
      </div>
    </PreviewFrame>
  );
}

export function CsvPreview({ content }: { content: string }) {
  const rows = useMemo(() => parseCsv(content, 501), [content]);
  const [head = [], ...body] = rows;
  const columns = Math.min(
    80,
    rows.reduce((n, r) => Math.max(n, r.length), 0),
  );
  return (
    <PreviewFrame
      label={`csv · ${body.length}${body.length >= 500 ? '+' : ''} rows previewed`}
      copy={content}
    >
      <table className="min-w-full border-collapse text-left text-xs text-text">
        <thead className="sticky top-0 z-[1] bg-surface-sunken">
          <tr>
            {Array.from({ length: columns }, (_, c) => (
              <th
                key={c}
                scope="col"
                className="whitespace-nowrap border-b border-r border-border px-3 py-2 font-semibold last:border-r-0"
              >
                {head[c] ?? ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="num">
          {body.map((row, r) => (
            <tr key={r} className="even:bg-surface-sunken/40">
              {Array.from({ length: columns }, (_, c) => (
                <td
                  key={c}
                  className="max-w-[22rem] whitespace-pre-wrap border-b border-r border-border/70 px-3 py-1.5 align-top last:border-r-0"
                >
                  {row[c] ?? ''}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </PreviewFrame>
  );
}

export function PdfPreview({ url, name }: { url: string; name: string }) {
  const [loaded, setLoaded] = useState(false);
  useEffect(() => setLoaded(false), [url]);
  return (
    <div className="relative h-full min-h-[24rem] overflow-hidden rounded-xl border border-border bg-surface">
      {!loaded && <PreviewLoading label="Opening PDF preview…" />}
      <iframe
        key={url}
        title={name}
        src={url}
        onLoad={() => setLoaded(true)}
        className={cn('size-full border-0', !loaded && 'opacity-0')}
      />
    </div>
  );
}

export function ImagePreview({ url, name }: { url: string; name: string }) {
  return (
    <div className="grid h-full min-h-[16rem] place-items-center overflow-auto rounded-xl border border-border bg-surface p-3">
      <img src={url} alt={name} className="max-h-full max-w-full rounded-lg object-contain" />
    </div>
  );
}

/** Our tokens as plain CSS colours for the sandboxed DOCX frame (it cannot see our variables). */
function frameColours() {
  const style = getComputedStyle(document.documentElement);
  const rgb = (name: string, alpha = 1) =>
    `rgb(${style.getPropertyValue(name).trim() || '0 0 0'} / ${alpha})`;
  return { text: rgb('--foreground'), bg: rgb('--surface'), border: rgb('--border'), link: rgb('--primary') };
}

export function DocxPreview({ blob, name }: { blob: Blob; name: string }) {
  const html = useQuery({
    queryKey: ['file-preview', 'docx', name, blob.size, blob.type],
    queryFn: async () => {
      const mammoth = await import('mammoth');
      const result = await mammoth.convertToHtml({ arrayBuffer: await blob.arrayBuffer() });
      return result.value;
    },
    staleTime: Infinity,
    retry: false,
  });
  if (html.isPending) return <PreviewLoading label="Converting the document…" />;
  if (html.isError)
    return (
      <PreviewMessage
        tone="error"
        title="Could not open this document"
        description={html.error instanceof Error ? html.error.message : undefined}
      />
    );
  const c = frameColours();
  const doc = `<!doctype html><meta charset="utf-8"><style>body{font:14px/1.65 Inter,system-ui,sans-serif;margin:32px auto;max-width:46rem;padding:0 24px;color:${c.text};background:${c.bg}}table{border-collapse:collapse}td,th{border:1px solid ${c.border};padding:4px 8px}img{max-width:100%}a{color:${c.link}}</style>${html.data}`;
  return (
    <PreviewFrame label="word document" bodyClassName="overflow-hidden">
      <iframe title={name} srcDoc={doc} sandbox="" className="size-full border-0 bg-surface" />
    </PreviewFrame>
  );
}
