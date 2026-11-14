import { FolderTree } from 'lucide-react';
import { useState } from 'react';
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  FileDropzone,
  FileTree,
  Input,
  Skeleton,
  toast,
} from '@/shared/ui';
import { useSystemFiles, useUploadFiles } from '../../hooks/useSystems';
import { FilePreview } from './FilePreview';

export function FolderTab({ systemId }: { systemId: string }) {
  const files = useSystemFiles(systemId);
  const upload = useUploadFiles(systemId);
  const [selected, setSelected] = useState<string | null>('system-card.yaml');
  const [folder, setFolder] = useState('docs');

  const onFiles = (list: File[]) => {
    toast.promise(upload.mutateAsync({ files: list, folder }), {
      loading: `Uploading ${list.length} file${list.length === 1 ? '' : 's'}…`,
      success: (res) => {
        const changed = res.filter((r) => r.changed).length;
        if (res[0]) setSelected(res[0].file.path);
        return changed
          ? `Saved ${changed} new version${changed === 1 ? '' : 's'}`
          : 'No changes (same content)';
      },
      error: (e) => `Upload failed: ${e instanceof Error ? e.message : String(e)}`,
    });
  };

  if (files.error) return <ErrorState error={files.error} onRetry={() => files.refetch()} />;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(16rem,20rem)_1fr]">
      <div className="space-y-4">
        <Card className="p-2">
          <div className="flex items-center justify-between px-2 py-1.5">
            <span className="text-xs font-semibold text-text/80">/systems/{systemId}</span>
            {files.data && <Badge>{files.data.length} files</Badge>}
          </div>
          {files.isLoading ? (
            <div className="space-y-2 p-2">
              {Array.from({ length: 8 }, (_, i) => (
                <Skeleton key={i} className="h-5" style={{ width: `${60 + ((i * 17) % 35)}%` }} />
              ))}
            </div>
          ) : files.data?.length ? (
            <FileTree
              entries={files.data.map((f) => ({
                path: f.path,
                meta: f.version > 1 ? `v${f.version}` : undefined,
              }))}
              selected={selected}
              onSelect={setSelected}
            />
          ) : (
            <EmptyState compact icon={<FolderTree />} title="Empty folder" />
          )}
        </Card>
        <Card className="space-y-3 p-4">
          <div className="text-sm font-medium">Add files for the agent</div>
          <Input
            value={folder}
            onChange={(e) => setFolder(e.target.value)}
            placeholder="Target folder, e.g. docs or plugins/cv-ranker/docs"
            aria-label="Target folder"
          />
          <FileDropzone
            onFiles={onFiles}
            disabled={upload.isPending}
            accept=".md,.yaml,.yml,.json,.csv,.txt,.pdf"
            hint="Markdown, YAML, JSON, CSV, text or PDF. Each upload is a new version."
          />
        </Card>
      </div>
      <Card className="min-w-0 p-5">
        <FilePreview key={selected ?? ''} systemId={systemId} path={selected} />
      </Card>
    </div>
  );
}
