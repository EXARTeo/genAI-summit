import { Download, FileText, History, Maximize2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { blobFromBase64, classifyFile } from '@/shared/lib/files';
import { formatBytes, formatRelative } from '@/shared/lib/format';
import { cn } from '@/shared/lib/utils';
import {
  Badge,
  CodeBlock,
  DataTable,
  EmptyState,
  ErrorState,
  FilePreviewBody,
  FilePreviewPanel,
  IconButton,
  Markdown,
  SkeletonText,
  downloadPreviewFile,
  type DataTableColumn,
  type PreviewFile,
} from '@/shared/ui';
import { useFileVersions, useSystemFile } from '../../hooks/useSystems';
import { languageFor } from '../../lib/styles';
import { actorLabel } from '@/shared/lib/labels';

function parseCsv(text: string): { header: string[]; rows: string[][] } {
  // Small CSV reader: quoted fields with commas, "" escapes. Enough for previews.
  const rows: string[][] = [];
  for (const line of text.split(/\r?\n/).filter(Boolean)) {
    const out: string[] = [];
    let cur = '';
    let q = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (q) {
        if (ch === '"' && line[i + 1] === '"') {
          cur += '"';
          i++;
        } else if (ch === '"') q = false;
        else cur += ch;
      } else if (ch === '"') q = true;
      else if (ch === ',') {
        out.push(cur);
        cur = '';
      } else cur += ch;
    }
    out.push(cur);
    rows.push(out);
  }
  return { header: rows[0] ?? [], rows: rows.slice(1, 201) };
}

function CsvPreview({ text }: { text: string }) {
  const { header, rows } = parseCsv(text);
  const columns: DataTableColumn<string[]>[] = header.map((h, i) => ({
    id: String(i),
    header: h,
    cell: (r) => <span className="font-mono text-xs">{r[i]}</span>,
    sortValue: (r) => (r[i] !== '' && !Number.isNaN(Number(r[i])) ? Number(r[i]) : r[i]),
  }));
  return <DataTable columns={columns} rows={rows} rowKey={(r) => r.join('|')} maxHeight="28rem" />;
}

export function FilePreview({ systemId, path }: { systemId: string; path: string | null }) {
  const [version, setVersion] = useState<number | undefined>();
  const file = useSystemFile(systemId, path, version);
  const versions = useFileVersions(systemId, path);
  const [expanded, setExpanded] = useState(false);
  // The loaded version as a shared preview file (bytes from its text or base64).
  const data = file.data;
  const preview = useMemo<PreviewFile | null>(
    () =>
      data && path
        ? {
            id: `${systemId}:${path}@${data.version}`,
            name: path.split('/').pop() ?? path,
            mime: data.contentType,
            size: data.size,
            meta: [`v${data.version}`],
            load: async () =>
              data.text != null
                ? new Blob([data.text], { type: data.contentType })
                : blobFromBase64(data.dataB64 ?? '', data.contentType),
          }
        : null,
    [data, path, systemId],
  );

  if (!path) {
    return (
      <EmptyState
        icon={<FileText />}
        title="Pick a file"
        description="Select a file in the tree to preview it."
      />
    );
  }
  if (file.error) return <ErrorState compact error={file.error} onRetry={() => file.refetch()} />;

  const lang = languageFor(path);
  // Binary files (PDF, images, Word) render in the shared preview body.
  const kind = classifyFile({ name: path, mime: file.data?.contentType }).kind;
  const binary = file.data?.text === null || kind === 'pdf' || kind === 'image' || kind === 'docx';
  const text = file.data?.text ?? '';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm">{path}</span>
        {file.data && (
          <>
            <Badge tone="primary">v{file.data.version}</Badge>
            <Badge>{formatBytes(file.data.size)}</Badge>
            <span className="text-xs text-muted">
              by {actorLabel(file.data.createdBy)} · {formatRelative(file.data.createdAt)}
            </span>
          </>
        )}
        {preview && (
          <span className="ml-auto flex items-center gap-0.5">
            <IconButton
              label={`Open ${preview.name} in the preview`}
              icon={<Maximize2 />}
              onClick={() => setExpanded(true)}
            />
            <IconButton
              label={`Download ${preview.name}`}
              icon={<Download />}
              onClick={() => void downloadPreviewFile(preview)}
            />
          </span>
        )}
      </div>

      {file.isLoading ? (
        <SkeletonText lines={10} />
      ) : binary && preview ? (
        <div className="h-[32rem] overflow-hidden rounded-xl border border-border bg-surface-sunken p-3">
          <FilePreviewBody file={preview} onDownload={() => void downloadPreviewFile(preview)} />
        </div>
      ) : lang === 'markdown' ? (
        <div className="rounded-xl border border-border bg-surface p-5">
          <Markdown>{text}</Markdown>
        </div>
      ) : lang === 'csv' ? (
        <CsvPreview text={text} />
      ) : (
        <CodeBlock
          code={text}
          language={lang === 'yaml' || lang === 'json' ? lang : 'text'}
          title={path.split('/').pop()}
        />
      )}

      <FilePreviewPanel file={expanded ? preview : null} onClose={() => setExpanded(false)} />

      {(versions.data?.length ?? 0) > 1 && (
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-medium">
            <History className="size-4 text-muted" /> Versions
          </div>
          <ul className="space-y-1">
            {versions.data!.map((v) => {
              const selected = (version ?? versions.data![0].version) === v.version;
              return (
                <li key={v.version}>
                  <button
                    type="button"
                    onClick={() => setVersion(v.isCurrent ? undefined : v.version)}
                    className={cn(
                      'flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left text-sm transition-colors',
                      selected ? 'bg-primary/10 text-primary' : 'hover:bg-surface-muted',
                    )}
                  >
                    <span className="font-mono text-xs">v{v.version}</span>
                    {v.isCurrent && <Badge tone="success">current</Badge>}
                    <span className="truncate text-muted">{actorLabel(v.createdBy)}</span>
                    <span className="ml-auto text-xs text-muted">{formatRelative(v.createdAt)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
