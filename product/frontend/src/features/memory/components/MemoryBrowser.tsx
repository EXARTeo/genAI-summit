import { Brain, Search } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { formatRelative } from '@/shared/lib/format';
import { cn } from '@/shared/lib/utils';
import { Card, EmptyState, ErrorState, Input, Skeleton, StatusPill } from '@/shared/ui';
import { useMemoryLedger } from '../hooks/useMemory';
import { STATUS_TONE, filterMemory } from '../lib/memory';
import type { MemoryFilter } from '../lib/types';
import { MemoryDetail } from './MemoryDetail';

export interface MemoryBrowserProps {
  /** Fixed scope: "org" (Settings → Organisation rules) or "system:SYS-001" (System → Lessons). */
  scope: string;
  emptyTitle: ReactNode;
  emptyDescription?: ReactNode;
}

/**
 * Master/detail list of memory entries for one scope. The selected entry lives in `?entry=`.
 * Used in context (System → Lessons, Settings → Organisation rules), never as a top-level page.
 */
export function MemoryBrowser({ scope, emptyTitle, emptyDescription }: MemoryBrowserProps) {
  const { data, isLoading, error, refetch } = useMemoryLedger();
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState<MemoryFilter>({ scope, status: 'all', query: '' });
  const entries = useMemo(() => filterMemory(data ?? [], { ...filter, scope }), [data, filter, scope]);
  const selectedId = params.get('entry') ?? entries[0]?.id;
  const selected = data?.find((e) => e.id === selectedId && e.scope === scope) ?? entries[0];

  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (isLoading || !data) {
    return (
      <div className="grid gap-4 lg:grid-cols-[minmax(280px,360px)_1fr]">
        <div className="space-y-2">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
        <Skeleton className="h-80 rounded-xl" />
      </div>
    );
  }
  const total = data.filter((e) => e.scope === scope).length;
  if (total === 0) {
    return <EmptyState icon={<Brain />} title={emptyTitle} description={emptyDescription} />;
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(280px,360px)_1fr]">
      <div className="min-w-0 space-y-3">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
            <Input
              className="h-8 pl-8"
              placeholder="Filter"
              aria-label="Filter memory"
              value={filter.query}
              onChange={(e) => setFilter((f) => ({ ...f, query: e.target.value }))}
            />
          </div>
          <div
            className="flex rounded-lg bg-surface-muted p-0.5 text-xs"
            role="radiogroup"
            aria-label="Status"
          >
            {(['all', 'active', 'proposed', 'stale'] as const).map((s) => (
              <button
                key={s}
                type="button"
                role="radio"
                aria-checked={filter.status === s}
                onClick={() => setFilter((f) => ({ ...f, status: s }))}
                className={cn(
                  'rounded-md px-2 font-medium capitalize text-muted transition-colors',
                  filter.status === s && 'bg-surface text-text shadow-card',
                )}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        <Card className="divide-y divide-border overflow-hidden">
          {entries.length === 0 && <div className="p-6 text-center text-sm text-muted">No matches.</div>}
          {entries.map((e) => (
            <button
              key={e.id}
              type="button"
              onClick={() =>
                setParams(
                  (p) => {
                    p.set('entry', e.id);
                    return p;
                  },
                  { replace: true },
                )
              }
              className={cn(
                'relative block w-full px-3.5 py-3 text-left transition-colors hover:bg-surface-muted/60',
                e.id === selected?.id && 'bg-surface-muted/80',
              )}
            >
              {e.id === selected?.id && (
                <span className="absolute inset-y-2 left-0 w-0.5 rounded-r bg-primary" />
              )}
              <div className="flex items-center gap-2">
                <span className="num font-mono text-xs text-muted">{e.id}</span>
                <StatusPill status={e.status} tone={STATUS_TONE[e.status]} />
                <span className="num ml-auto text-2xs text-muted">used {e.usageCount}×</span>
              </div>
              <div className="mt-1 line-clamp-2 text-sm">{e.humanDecision}</div>
              <div className="mt-0.5 text-2xs text-muted">
                {e.reasonCategory.replace(/_/g, ' ')} · {e.author} · {formatRelative(e.createdAt)}
              </div>
            </button>
          ))}
        </Card>
      </div>
      <Card className="h-fit min-w-0 p-5 lg:sticky lg:top-[calc(var(--topbar-height)+1rem)]">
        {selected ? (
          <MemoryDetail entry={selected} all={data} />
        ) : (
          <EmptyState compact title="Pick an entry" />
        )}
      </Card>
    </div>
  );
}
