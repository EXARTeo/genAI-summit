import { FolderTree, Upload } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMediaQuery } from '@/shared/hooks/useMediaQuery';
import { formatBytes, formatRelative } from '@/shared/lib/format';
import { actorLabel } from '@/shared/lib/labels';
import { EmptyState, ErrorState, FileTree, Skeleton, toast } from '@/shared/ui';
import { useFillHeight } from '../../hooks/useFillHeight';
import { useSystemFiles, useUploadFiles } from '../../hooks/useSystems';
import { systemRoutes } from '../../lib/routes';
import { FilePreview } from './FilePreview';

const ACCEPT = '.md,.yaml,.yml,.json,.csv,.txt,.pdf';

/** Plugins (one folder per model) are configured in the Plugins tab, not edited as files. */
const isPluginPath = (path: string) => path === 'plugins' || path.startsWith('plugins/');

/** The system dossier as one explorer: tree (add files per folder, drag-and-drop) + full-height viewer. */
export function FolderTab({ systemId }: { systemId: string }) {
  // Wide screens: the explorer runs to the bottom of the window; both panes scroll inside it.
  const wide = useMediaQuery('(min-width: 1024px)');
  const fill = useFillHeight<HTMLDivElement>(480, 32);
  const files = useSystemFiles(systemId);
  const visible = useMemo(() => (files.data ?? []).filter((f) => !isPluginPath(f.path)), [files.data]);
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
    <div
      ref={fill.ref}
      style={wide ? { height: fill.height } : undefined}
      className="grid overflow-hidden rounded-2xl border border-border bg-surface shadow-sm lg:grid-cols-[18.75rem_minmax(0,1fr)] lg:grid-rows-1"
    >
      <div className="relative min-h-0 border-b border-border lg:border-b-0 lg:border-r">
        <aside className="flex max-h-[45vh] min-h-0 flex-col bg-surface-sunken/60 lg:absolute lg:inset-0 lg:max-h-none">
          <div className="flex items-center justify-between gap-2 px-4 pb-2 pt-3">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">Explorer</span>
            {files.data && (
              <span className="text-[11px] tabular-nums text-muted">
                {visible.length} file{visible.length === 1 ? '' : 's'}
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
                  entries={visible.map((f) => ({
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
                {!visible.length && (
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
          <div className="space-y-1 border-t border-border px-4 py-2 text-[11px] text-muted">
            <p className="hidden lg:block">
              Hover a folder to add files, or drop files on it. Each upload is a new version.
            </p>
            <p>
              Models are wrapped as plugins, configured in the{' '}
              <Link
                to={systemRoutes.detail(systemId, 'plugins')}
                className="font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Plugins tab
              </Link>
              .
            </p>
          </div>
        </aside>
      </div>
      <section className="flex min-h-[28rem] min-w-0 flex-col lg:min-h-0">
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
