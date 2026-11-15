import { AnimatePresence, motion } from 'framer-motion';
import { ChevronRight, FileMinus2, FilePen, FilePlus2, FileText } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { collapse } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';
import { Badge, Skeleton } from '@/shared/ui';
import { useDocDiff, useProvisionAt } from '../hooks/useRegulation';
import { collapseContext, diffCounts, lineDiff, parseUnified } from '../lib/diff';
import { provisionLabel, topProvisionId } from '../lib/regulation';
import type { ChangeFile, DiffRow, Provision } from '../lib/types';
import { DiffStat, DiffView, type DiffMode } from './DiffView';

interface FileProps {
  file: ChangeFile;
  fromKb: string | null;
  toKb: string;
  isNew: boolean;
  open: boolean;
  mode: DiffMode;
  onToggle: () => void;
}

/** One "file changed" of a regulation change: a collapsible header and its diff. */
export function ChangeFileDiff(props: FileProps) {
  const { file, open, isNew, onToggle } = props;
  const prov = useProvisionPair(file, props.fromKb, props.toKb, open);
  const doc = useDocDiff(
    file.kind === 'document' ? file.docId : undefined,
    file.kind === 'document' ? file.from : 0,
    file.kind === 'document' ? file.to : 0,
  );
  const rows = useMemo<DiffRow[] | null>(() => {
    if (file.kind === 'document') return doc.data ? parseUnified(doc.data.unified) : null;
    if (file.kind === 'provision' && prov.ready) return lineDiff(prov.old?.text ?? '', prov.new?.text ?? '');
    return null;
  }, [file.kind, doc.data, prov.ready, prov.old, prov.new]);
  const stat = rows ? diffCounts(rows) : null;
  const status: 'added' | 'removed' | 'modified' | null =
    file.kind !== 'provision' || !prov.ready
      ? null
      : !prov.old
        ? 'added'
        : !prov.new
          ? 'removed'
          : 'modified';
  const Icon =
    status === 'added'
      ? FilePlus2
      : status === 'removed'
        ? FileMinus2
        : file.kind === 'document'
          ? FileText
          : FilePen;

  return (
    <div className={cn('border-b border-border last:border-b-0', open && 'bg-surface')}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full min-w-0 items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-hover sm:px-4"
      >
        <ChevronRight
          className={cn('size-3.5 shrink-0 text-muted transition-transform', open && 'rotate-90')}
        />
        <Icon
          className={cn(
            'size-3.5 shrink-0',
            status === 'added' ? 'text-success' : status === 'removed' ? 'text-danger' : 'text-muted',
          )}
        />
        <span
          className={cn(
            'min-w-0 truncate font-mono text-xs',
            isNew ? 'font-semibold text-text' : 'text-text/80',
          )}
        >
          {file.kind === 'document' ? `${file.docId}  v${file.from} → v${file.to}` : file.id}
        </span>
        {file.kind !== 'document' && (
          <span className="hidden truncate text-2xs text-muted sm:inline">{provisionLabel(file.id)}</span>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-2">
          {isNew && (
            <Badge tone="primary" className="h-4 px-1 text-[10px] uppercase tracking-wide">
              New
            </Badge>
          )}
          {stat && <DiffStat {...stat} />}
        </span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            variants={collapse}
            initial="initial"
            animate="animate"
            exit="exit"
            className="overflow-hidden"
          >
            <div className="border-t border-border/70">
              <FileBody {...props} rows={rows} prov={prov} docLoading={doc.isLoading} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function useProvisionPair(file: ChangeFile, fromKb: string | null, toKb: string, open: boolean) {
  const id = file.kind === 'provision' ? file.id : '';
  const enabled = open && file.kind === 'provision';
  const old = useProvisionAt(id, fromKb, enabled);
  const neu = useProvisionAt(id, toKb, enabled);
  const ready = old.isSuccess && neu.isSuccess;
  return {
    ready,
    loading: enabled && (old.isLoading || neu.isLoading),
    error: old.error ?? neu.error,
    old: old.data ?? null,
    new: neu.data ?? null,
    noBase: !fromKb,
  };
}

function FileBody({
  file,
  rows,
  prov,
  docLoading,
  mode,
}: FileProps & { rows: DiffRow[] | null; prov: ReturnType<typeof useProvisionPair>; docLoading: boolean }) {
  const [expanded, setExpanded] = useState(false);
  if (file.kind === 'opaque') {
    return (
      <p className="px-4 py-3 text-xs text-muted">
        An interpretation node of the source; its text lives in the source document, not in the provision
        store.
      </p>
    );
  }
  if (file.kind === 'provision' && prov.noBase) {
    return <p className="px-4 py-3 text-xs text-muted">No earlier kb release to compare with.</p>;
  }
  if (prov.loading || docLoading) return <Skeleton className="m-3 h-20" />;
  if (prov.error) return <p className="px-4 py-3 text-xs text-danger">Could not load this provision.</p>;
  if (!rows) return <p className="px-4 py-3 text-xs text-muted">No diff available.</p>;
  const changed = rows.some((r) => r.type === 'add' || r.type === 'del');
  const shown = expanded ? rows : collapseContext(rows, 3);
  return (
    <div>
      {changed ? (
        <DiffView rows={shown} mode={mode} />
      ) : (
        <p className="px-4 py-3 text-xs text-muted">
          The text is identical; the change is in the provision&apos;s metadata.
        </p>
      )}
      {file.kind === 'provision' && <MetaDiff old={prov.old} neu={prov.new} />}
      <div className="flex flex-wrap items-center gap-3 border-t border-border/60 px-4 py-1.5 text-2xs text-muted">
        {changed && shown.length !== rows.length && (
          <button type="button" className="hover:text-text hover:underline" onClick={() => setExpanded(true)}>
            Show full text
          </button>
        )}
        {file.kind === 'provision' && (prov.new ?? prov.old)?.source_doc && (
          <Link
            to={`/regulation/sources/${encodeURIComponent((prov.new ?? prov.old)!.source_doc!)}?p=${encodeURIComponent(topProvisionId(file.id))}`}
            className="hover:text-text hover:underline"
          >
            Open in source reader →
          </Link>
        )}
        {file.kind === 'document' && (
          <Link
            to={`/regulation/sources/${encodeURIComponent(file.docId)}?mode=changes`}
            className="hover:text-text hover:underline"
          >
            Open in source reader →
          </Link>
        )}
      </div>
    </div>
  );
}

function MetaDiff({ old, neu }: { old: Provision | null; neu: Provision | null }) {
  if (!old || !neu) return null;
  const fields: [string, string, string][] = [
    ['title', old.title ?? '', neu.title ?? ''],
    ['valid from', old.valid_from ?? '', neu.valid_from ?? ''],
    ['amended by', (old.amended_by ?? []).join(', '), (neu.amended_by ?? []).join(', ')],
  ];
  const diffs = fields.filter(([, a, b]) => a !== b);
  if (diffs.length === 0) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t border-border/60 px-4 py-2 text-2xs">
      {diffs.map(([k, a, b]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words font-mono">
            <span className="text-danger line-through">{a || '–'}</span> <span className="text-muted">→</span>{' '}
            <span className="text-success">{b || '–'}</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}
