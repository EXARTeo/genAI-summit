import { ArrowUpRight, Search } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { formatRelative } from '@/shared/lib/format';
import { cn } from '@/shared/lib/utils';
import { EmptyState, Input } from '@/shared/ui';
import { KIND_LABEL, SOURCE_GROUPS, groupOf, groupSources, matchesSource } from '../lib/reader';
import { latestVersion } from '../lib/regulation';
import type { RegSource } from '../lib/types';

/** Every source as a calm panel, grouped by kind; a panel opens the source reader. */
export function SourcesGrid({ sources }: { sources: RegSource[] }) {
  const [q, setQ] = useState('');
  const [group, setGroup] = useState<string>('all');
  const filtered = sources.filter(
    (s) => matchesSource(s, q) && (group === 'all' || groupOf(s.kind).key === group),
  );
  const groups = groupSources(filtered);
  const counts = new Map(
    SOURCE_GROUPS.map((g) => [g.key, sources.filter((s) => groupOf(s.kind).key === g.key).length]),
  );

  return (
    <div>
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="w-full sm:max-w-xs">
          <Input
            leftIcon={<Search />}
            placeholder="Search sources"
            aria-label="Search sources"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="-mx-4 flex gap-1 overflow-x-auto px-4 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:px-0">
          {[{ key: 'all', label: 'All' }, ...SOURCE_GROUPS.filter((g) => (counts.get(g.key) ?? 0) > 0)].map(
            (g) => (
              <button
                key={g.key}
                type="button"
                aria-pressed={group === g.key}
                onClick={() => setGroup(g.key)}
                className={cn(
                  'shrink-0 whitespace-nowrap rounded-full border px-3 py-1 text-xs transition-colors',
                  group === g.key
                    ? 'border-text/80 bg-text text-background'
                    : 'border-border text-muted hover:border-text/30 hover:text-text',
                )}
              >
                {g.label}
                <span className="ml-1.5 tabular-nums opacity-60">
                  {g.key === 'all' ? sources.length : counts.get(g.key)}
                </span>
              </button>
            ),
          )}
        </div>
      </div>

      {groups.length === 0 && (
        <EmptyState compact title="No source matches" description="Try another word or kind." />
      )}

      <div className="space-y-10">
        {groups.map(({ group: g, items }) => (
          <section key={g.key} aria-labelledby={`grp-${g.key}`}>
            <div className="mb-3 flex items-baseline gap-3 border-b border-border pb-2">
              <h2 id={`grp-${g.key}`} className="font-heading text-xl font-medium">
                {g.label}
              </h2>
              <span className="text-xs text-muted">{g.blurb}</span>
              <span className="ml-auto font-mono text-2xs text-muted">{items.length}</span>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {items.map((s) => (
                <SourcePanel key={s.id} s={s} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function SourcePanel({ s }: { s: RegSource }) {
  const last = s.versions[s.versions.length - 1];
  const v = latestVersion(s);
  const changed = s.versions.some((x) => x.status === 'changed');
  const binding = s.binding === true;
  return (
    <Link
      to={`/regulation/sources/${encodeURIComponent(s.id)}`}
      className={cn(
        'group relative flex min-h-[9.5rem] flex-col rounded-lg border border-border bg-surface p-4 transition-all',
        'hover:-translate-y-px hover:border-text/25 hover:shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
      )}
    >
      {binding && <span className="absolute inset-y-3 left-0 w-0.5 rounded-full bg-primary/70" aria-hidden />}
      <div className="flex items-center gap-2 text-2xs uppercase tracking-wider text-muted">
        <span>{KIND_LABEL[s.kind]}</span>
        <span aria-hidden>·</span>
        <span className={cn(binding ? 'text-primary' : s.binding === 'internal' ? 'text-info' : '')}>
          {binding ? 'Binding' : s.binding === 'internal' ? 'Internal' : 'Non-binding'}
        </span>
        {s.status === 'draft' && (
          <>
            <span aria-hidden>·</span>
            <span className="text-warning">Draft</span>
          </>
        )}
        <ArrowUpRight className="ml-auto size-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
      </div>
      <h3 className="mt-2 line-clamp-3 font-heading text-lg font-medium leading-snug [overflow-wrap:anywhere]">
        {s.title}
      </h3>
      <div className="mt-auto flex items-center gap-2 pt-3 text-2xs text-muted">
        <span className="truncate">{s.publisher || s.id}</span>
        <span className="ml-auto shrink-0 font-mono tabular-nums">
          {v > 0 ? `v${v}` : 'not fetched'}
          {changed && <span className="ml-1 text-warning">●</span>}
        </span>
        {last?.fetchedAt && <span className="shrink-0">{formatRelative(last.fetchedAt)}</span>}
      </div>
    </Link>
  );
}
