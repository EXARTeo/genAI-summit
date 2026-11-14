/**
 * The attachment preview (magenticx `features/attachments/AttachmentPreviewPanel.tsx` +
 * `attachment_preview_parts/*`): a side sheet that shows a file by kind. Images inline, PDF in the
 * browser viewer, DOCX converted in the browser (mammoth) into a sandboxed frame, Markdown
 * rendered, CSV as a table, JSON / code highlighted, text as is. A sent file is fetched through
 * `GET /v1/attachments/preview/...` (the anonymous client header goes with it); a composer file is
 * read locally.
 */
import { useQuery } from '@tanstack/react-query';
import { Download, FolderInput } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Button, ErrorState, Sheet, Skeleton } from '@/shared/ui';
import { previewAttachmentBlob } from '../handlers/chat';
import { codeLanguage, formatBytes, imageSrc, previewKind } from '../lib/attachments';
import { useChatUi, type PreviewTarget } from './chatContext';
import { ChatMarkdown } from './message_parts/ChatMarkdown';
import { downloadAttachment } from './message_parts/MessageAttachments';
import { saveAttachmentToSystem } from '../handlers/chat';
import { toast } from '@/shared/ui';

const TEXT_LIMIT = 400_000;

function parseCsv(text: string): string[][] {
  return text
    .trim()
    .split(/\r?\n/)
    .slice(0, 500)
    .map((line) => {
      const out: string[] = [];
      let cur = '';
      let quoted = false;
      for (let i = 0; i < line.length; i += 1) {
        const c = line[i];
        if (c === '"') {
          if (quoted && line[i + 1] === '"') {
            cur += '"';
            i += 1;
          } else quoted = !quoted;
        } else if (c === ',' && !quoted) {
          out.push(cur);
          cur = '';
        } else cur += c;
      }
      out.push(cur);
      return out;
    });
}

function useObjectUrl(blob: Blob | null | undefined) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob) {
      setUrl(null);
      return;
    }
    const u = URL.createObjectURL(blob);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [blob]);
  return url;
}

function DocxView({ blob, name }: { blob: Blob; name: string }) {
  const html = useQuery({
    queryKey: ['chat', 'docx', name, blob.size],
    queryFn: async () => {
      const mammoth = await import('mammoth');
      const result = await mammoth.convertToHtml({ arrayBuffer: await blob.arrayBuffer() });
      return result.value;
    },
  });
  if (html.isPending) return <Skeleton className="h-[70vh] w-full" />;
  if (html.isError) return <ErrorState title="Could not open this document" error={html.error} />;
  const doc = `<!doctype html><meta charset="utf-8"><style>body{font:14px/1.6 system-ui,sans-serif;margin:24px;color:#18181b;background:#fff}table{border-collapse:collapse}td,th{border:1px solid #e4e4e7;padding:4px 8px}img{max-width:100%}</style>${html.data}`;
  return (
    <iframe
      title={name}
      srcDoc={doc}
      sandbox=""
      className="h-[75vh] w-full rounded-lg border border-border bg-white"
    />
  );
}

function Body({ blob, name, mime }: { blob: Blob; name: string; mime: string }) {
  const kind = previewKind({ name, mime });
  const url = useObjectUrl(blob);
  const text = useQuery({
    queryKey: ['chat', 'preview-text', name, blob.size],
    queryFn: async () => (await blob.slice(0, TEXT_LIMIT).text()) as string,
    enabled: ['markdown', 'csv', 'json', 'code', 'text'].includes(kind),
  });
  if (kind === 'image')
    return url ? (
      <img src={url} alt={name} className="mx-auto max-h-[75vh] rounded-lg border border-border" />
    ) : null;
  if (kind === 'pdf')
    return url ? (
      <iframe title={name} src={url} className="h-[75vh] w-full rounded-lg border border-border" />
    ) : null;
  if (kind === 'docx') return <DocxView blob={blob} name={name} />;
  if (kind === 'unsupported')
    return <p className="text-sm text-muted">No preview for this file type. Download it to open it.</p>;
  if (text.isPending) return <Skeleton className="h-64 w-full" />;
  const value = text.data ?? '';
  if (kind === 'markdown') return <ChatMarkdown text={value} />;
  if (kind === 'csv') {
    const [head, ...rows] = parseCsv(value);
    return (
      <div className="overflow-auto rounded-lg border border-border">
        <table className="w-full text-xs">
          <thead className="bg-surface-muted text-muted">
            <tr>
              {head?.map((h, i) => (
                <th key={i} className="px-3 py-1.5 text-left font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="num">
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-border">
                {r.map((c, j) => (
                  <td key={j} className="px-3 py-1.5">
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (kind === 'json' || kind === 'code') {
    let code = value;
    if (kind === 'json') {
      try {
        code = JSON.stringify(JSON.parse(value), null, 2);
      } catch {
        /* show as is */
      }
    }
    return (
      <ChatMarkdown
        text={`\`\`\`${kind === 'json' ? 'json' : (codeLanguage(name) ?? '')}\n${code}\n\`\`\``}
      />
    );
  }
  return (
    <pre className="whitespace-pre-wrap rounded-lg bg-surface-muted p-3 font-mono text-xs leading-relaxed">
      {value}
    </pre>
  );
}

export function AttachmentPreview({
  target,
  onClose,
}: {
  target: PreviewTarget | null;
  onClose: () => void;
}) {
  const { conversationId, systemId, systemName } = useChatUi();
  const meta = target?.attachment;
  const sent = target?.kind === 'sent' ? target : null;
  const blob = useQuery({
    queryKey: ['chat', 'attachment', sent?.attachment.id ?? ''],
    enabled: Boolean(sent && conversationId && sent.attachment.blobId && !imageSrc(sent.attachment)),
    staleTime: Infinity,
    queryFn: () =>
      previewAttachmentBlob(conversationId as string, sent!.messageId, sent!.attachment.blobId as string),
  });
  const resolved: Blob | null = useMemo(() => {
    if (!target) return null;
    if (target.kind === 'pending') return target.attachment.file;
    const data = target.attachment.data;
    if (data) {
      const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
      return new Blob([bytes], { type: target.attachment.mime });
    }
    return blob.data ?? null;
  }, [target, blob.data]);

  const save = async () => {
    if (!sent || !systemId) return;
    try {
      const res = await saveAttachmentToSystem(systemId, sent.attachment.id);
      toast.success(`Saved to ${systemName ?? systemId}: ${res.file.path}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save the file');
    }
  };

  return (
    <Sheet
      open={Boolean(target)}
      onOpenChange={(open) => !open && onClose()}
      title={meta?.name ?? 'Preview'}
      description={meta ? [formatBytes(meta.size), meta.mime].filter(Boolean).join(' · ') : undefined}
      width="w-[min(48rem,100vw)]"
      footer={
        sent ? (
          <>
            {systemId && (
              <Button variant="secondary" size="sm" leftIcon={<FolderInput />} onClick={() => void save()}>
                Save to {systemName ?? systemId} folder
              </Button>
            )}
            <Button
              size="sm"
              leftIcon={<Download />}
              disabled={!conversationId || !sent.attachment.blobId}
              onClick={() =>
                conversationId && void downloadAttachment(conversationId, sent.messageId, sent.attachment)
              }
            >
              Download
            </Button>
          </>
        ) : undefined
      }
    >
      {blob.isError ? (
        <ErrorState title="Could not load the file" error={blob.error} onRetry={() => void blob.refetch()} />
      ) : resolved && meta ? (
        <Body blob={resolved} name={meta.name} mime={meta.mime} />
      ) : (
        <Skeleton className="h-64 w-full" />
      )}
    </Sheet>
  );
}
