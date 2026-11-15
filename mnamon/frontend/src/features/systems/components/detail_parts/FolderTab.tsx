import { FolderTree, Upload } from 'lucide-react';
import { useRef, useState } from 'react';
import { formatBytes, formatRelative } from '@/shared/lib/format';
import { actorLabel } from '@/shared/lib/labels';
import { EmptyState, ErrorState, FileTree, Skeleton, toast } from '@/shared/ui';
import { useSystemFiles, useUploadFiles } from '../../hooks/useSystems';
import { FilePreview } from './FilePreview';

const ACCEPT = '.md,.yaml,.yml,.json,.csv,.txt,.pdf';

/** The system dossier as one explorer: tree (add files per folder, drag-and-drop) + full-height viewer. */
export function FolderTab({ systemId }: { systemId: string }) {
  const files = useSystemFiles(systemId);
  const upload = useUploadFiles(systemId);
  const [selected, setSelected] = useState<string | null>('system-card.yaml');
  const [busyFolder, setBusyFolder] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const pickFor = useRef('');

  const onFiles = (folder: string, list: File[]) => {
    if (!list.length || upload.isPending) return;
    setBusyFolder(folder);
    const where = folder ? `${folder}/` : 'the root';
    toast.promise(upload.mutateAsync({ files: list, folder }), {
      loading: `Uploading ${list.length} file${list.length === 1 ? '' : 's'} to ${where}…`,
      success: (res) => {
        const changed = res.filter((r) => r.changed).length;
        if (res[0]) setSelected(res[0].file.path);
        return changed
          ? `Saved ${changed} new version${changed === 1 ? '' : 's'} in ${where}`
          : 'No changes (same content)';
      },
      error: (e) => `Upload failed: ${e instanceof Error ? e.message : String(e)}`,
      finally: () => setBusyFolder(null),
    });
  };

  const openPicker = (folder: string) => {
    pickFor.current = folder;
    picker.current?.click();
  };

  if (files.error) return <ErrorState error={files.error} onRetry={() => files.refetch()} />;

  const addButton = (folder: string) => {
    const label = `Add files to ${folder ? `${folder}/` : `/systems/${systemId}`}`;
    return (
      <button
        type="button"
        aria-label={label}
        title={label}
        disabled={upload.isPending}
        onClick={() => openPicker(folder)}
        className="grid size-6 place-items-center rounded-md text-muted transition-colors hover:bg-primary/10 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 [&_svg]:size-3.5"
      >
        <Upload />
      </button>
    );
  };

  return (
    <div className="grid overflow-hidden rounded-2xl border border-border bg-surface shadow-sm lg:h-[calc(100dvh-8rem)] lg:min-h-[34rem] lg:grid-cols-[18.75rem_minmax(0,1fr)]">
      <aside className="flex max-h-[45vh] min-h-0 flex-col border-b border-border bg-surface-sunken/60 lg:max-h-none lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between gap-2 px-4 pb-2 pt-3">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">Explorer</span>
          {files.data && (
            <span className="text-[11px] tabular-nums text-muted">
              {files.data.length} file{files.data.length === 1 ? '' : 's'}
            </span>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {files.isLoading ? (
            <div className="space-y-2 p-2">
              {Array.from({ length: 8 }, (_, i) => (
                <Skeleton key={i} className="h-5" style={{ width: `${60 + ((i * 17) % 35)}%` }} />
              ))}
            </div>
          ) : (
            <>
              <FileTree
                className="min-h-full pb-6"
                rootLabel={<span className="font-mono text-xs">/systems/{systemId}</span>}
                showCounts
                entries={(files.data ?? []).map((f) => ({
                  path: f.path,
                  title: `v${f.version} · ${formatBytes(f.size)} · by ${actorLabel(f.createdBy)} · ${formatRelative(f.createdAt)}`,
                  meta: (
                    <span className="flex items-center gap-1.5">
                      <span className="hidden group-hover:inline">{formatBytes(f.size)}</span>
                      {f.version > 1 && (
                        <span className="rounded bg-primary/10 px-1 font-medium text-primary">
                          v{f.version}
                        </span>
                      )}
                    </span>
                  ),
                }))}
                selected={selected}
                onSelect={setSelected}
                folderAction={addButton}
                onDropFiles={onFiles}
                busyFolder={busyFolder}
              />
              {!files.data?.length && (
                <EmptyState
                  compact
                  icon={<FolderTree />}
                  title="Empty folder"
                  description="Drop files here or use the upload button."
                />
              )}
            </>
          )}
        </div>
        <p className="hidden border-t border-border px-4 py-2 text-[11px] text-muted lg:block">
          Hover a folder to add files, or drop files on it. Each upload is a new version.
        </p>
      </aside>
      <section className="min-h-[28rem] min-w-0 lg:min-h-0">
        <FilePreview key={selected ?? ''} systemId={systemId} path={selected} />
      </section>
      <input
        ref={picker}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        data-testid="folder-file-input"
        onChange={(e) => {
          onFiles(pickFor.current, Array.from(e.target.files ?? []));
          e.target.value = '';
        }}
      />
    </div>
  );
}
