import { ArrowLeft, Check, Columns2, GitCommitHorizontal, Rows3, X } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { formatDateTime, formatRelative } from '@/shared/lib/format';
import { cn } from '@/shared/lib/utils';
import { Badge, Button, StatusPill, toast } from '@/shared/ui';
import { useDecideChange, useReleases } from '../hooks/useRegulation';
import { useUnread } from '../hooks/useSeen';
import { seenStore } from '../lib/seen';
import { changeFiles, parentKb } from '../lib/regulation';
import type { RegChange } from '../lib/types';
import { ChangeFileDiff } from './ChangeFileDiff';
import type { DiffMode } from './DiffView';
import { ImpactPanel } from './ImpactPanel';

const FIRST = 8;

/** One regulation change, read like a commit: header, files changed with their diffs, then impact. */
export function ChangeDetail({ c, onBack }: { c: RegChange; onBack?: () => void }) {
  const files = changeFiles(c);
  const releases = useReleases();
  const fromKb = parentKb(releases.data, c.candidateKbVersion);
  const unread = useUnread([c]);
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [showAll, setShowAll] = useState(false);
  const [mode, setMode] = useState<DiffMode>('unified');
  const decide = useDecideChange();
  const shown = showAll ? files : files.slice(0, FIRST);
  const newFiles = unread.newFiles(c);

  const toggle = (key: string) => {
    seenStore.markFile(c.id, key);
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };
  const expandShown = () => {
    shown.forEach((f) => seenStore.markFile(c.id, f.key));
    setOpen(new Set(shown.map((f) => f.key)));
  };

  return (
    <article className="min-w-0">
      {onBack && (
        <button
          type="button"
          onClick={onBack}
          className="mb-3 inline-flex items-center gap-1 text-xs text-muted hover:text-text lg:hidden"
        >
          <ArrowLeft className="size-3.5" /> All changes
        </button>
      )}
      <header className="border-b border-border pb-4">
        <div className="flex flex-wrap items-center gap-2 text-2xs">
          <GitCommitHorizontal className="size-4 text-muted" />
          <span className="font-mono text-muted">{c.id}</span>
          <StatusPill status={c.status} />
          <Badge>{c.changeType.replace(/_/g, ' ')}</Badge>
          {unread.isNewChange(c) && <Badge tone="primary">New</Badge>}
        </div>
        <h2 className="mt-2 font-heading text-2xl font-medium leading-tight [overflow-wrap:anywhere] sm:text-3xl">
          {c.title}
        </h2>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          <Link
            to={`/regulation/sources/${encodeURIComponent(c.sourceId)}`}
            className="font-mono hover:text-text hover:underline"
          >
            {c.sourceId}
          </Link>
          <span className="font-mono">
            v{c.fromVersion} → v{c.toVersion}
          </span>
          <span className="font-mono">
            kb {fromKb ?? '?'} → {c.candidateKbVersion}
          </span>
          <span title={formatDateTime(c.detectedAt)}>detected {formatRelative(c.detectedAt)}</span>
        </div>
        {c.summary && c.summary !== c.title && (
          <p className="mt-3 max-w-prose text-sm leading-relaxed text-text/85">{c.summary}</p>
        )}
        {c.status === 'proposed' && (
          <div className="mt-4 flex flex-wrap items-center gap-2 rounded-md border border-warning/30 bg-warning/[0.06] px-3 py-2">
            <span className="mr-auto text-xs text-text/85">
              Review the diff, then accept the candidate kb release or reject the change.
            </span>
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<X />}
              loading={decide.isPending && decide.variables?.status === 'rejected'}
              onClick={() => decide.mutate({ id: c.id, status: 'rejected' })}
            >
              Reject
            </Button>
            <Button
              size="sm"
              leftIcon={<Check />}
              loading={decide.isPending && decide.variables?.status === 'accepted'}
              onClick={() =>
                decide.mutate(
                  { id: c.id, status: 'accepted' },
                  {
                    onSuccess: () =>
                      toast.success(`kb_version ${c.candidateKbVersion} accepted`, {
                        description: 'Old decisions are marked stale, never rewritten.',
                      }),
                  },
                )
              }
            >
              Accept kb {c.candidateKbVersion}
            </Button>
          </div>
        )}
      </header>

      <section aria-label="Files changed" className="py-4">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Files changed</h3>
          <span className="rounded-full bg-surface-sunken px-1.5 font-mono text-2xs tabular-nums">
            {files.length}
          </span>
          {newFiles > 0 && <span className="text-2xs font-medium text-primary">{newFiles} not opened</span>}
          <span className="ml-auto flex items-center gap-1">
            <button
              type="button"
              onClick={open.size > 0 ? () => setOpen(new Set()) : expandShown}
              className="rounded px-2 py-1 text-2xs text-muted hover:bg-hover hover:text-text"
            >
              {open.size > 0
                ? 'Collapse all'
                : `Expand ${shown.length === files.length ? 'all' : `first ${shown.length}`}`}
            </button>
            <span className="hidden items-center rounded-md bg-surface-sunken p-0.5 sm:inline-flex">
              {(
                [
                  ['unified', Rows3],
                  ['split', Columns2],
                ] as const
              ).map(([m, Icon]) => (
                <button
                  key={m}
                  type="button"
                  aria-pressed={mode === m}
                  onClick={() => setMode(m)}
                  className={cn(
                    'inline-flex items-center gap-1 rounded px-2 py-0.5 text-2xs capitalize',
                    mode === m ? 'bg-surface text-text shadow-card' : 'text-muted hover:text-text',
                  )}
                >
                  <Icon className="size-3" /> {m}
                </button>
              ))}
            </span>
          </span>
        </div>
        {files.length === 0 ? (
          <p className="text-xs text-muted">reg-memory reported no changed provision.</p>
        ) : (
          <div className="overflow-hidden rounded-md border border-border bg-surface-sunken/30">
            {shown.map((f) => (
              <ChangeFileDiff
                key={f.key}
                file={f}
                fromKb={fromKb}
                toKb={c.candidateKbVersion}
                isNew={unread.isNewFile(c.id, f.key)}
                open={open.has(f.key)}
                mode={mode}
                onToggle={() => toggle(f.key)}
              />
            ))}
            {files.length > shown.length && (
              <button
                type="button"
                onClick={() => setShowAll(true)}
                className="w-full border-t border-border px-4 py-2 text-left text-xs font-medium text-primary hover:bg-hover"
              >
                Show all {files.length} files
              </button>
            )}
          </div>
        )}
      </section>

      <ImpactPanel c={c} />
    </article>
  );
}
