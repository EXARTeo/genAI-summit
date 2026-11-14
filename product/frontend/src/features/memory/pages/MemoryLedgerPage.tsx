import { motion } from 'framer-motion';
import { Brain, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { listItem, staggerList } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Input,
  PageHeader,
  Select,
  SkeletonCard,
  StatusPill,
} from '@/shared/ui';
import { MemoryDetail } from '../components/MemoryDetail';
import { useMemoryLedger } from '../hooks/useMemory';
import { STATUS_TONE, filterMemory, scopeLabel, scopesOf } from '../lib/memory';
import type { MemoryFilter } from '../lib/types';

export function MemoryLedgerPage() {
  const { data, isLoading, error, refetch } = useMemoryLedger();
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState<MemoryFilter>({ scope: 'all', status: 'all', query: '' });
  const entries = useMemo(() => filterMemory(data ?? [], filter), [data, filter]);
  const selectedId = params.get('entry') ?? entries[0]?.id;
  const selected = data?.find((e) => e.id === selectedId);

  return (
    <div>
      <PageHeader
        title="Memory"
        description="What the agents learned from human decisions, per system and org-wide. Every create, approve, promote, retire and read is logged."
        icon={<Brain />}
        meta={data && <Badge>{data.filter((e) => e.status === 'active').length} active</Badge>}
      />
      <div className="mb-4 flex flex-wrap gap-2">
        <div className="relative min-w-[14rem] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
          <Input
            className="pl-9"
            placeholder="Search memory"
            value={filter.query}
            onChange={(e) => setFilter((f) => ({ ...f, query: e.target.value }))}
          />
        </div>
        <Select
          className="w-44"
          aria-label="Scope"
          value={filter.scope}
          onValueChange={(v) => setFilter((f) => ({ ...f, scope: v }))}
          options={[
            { value: 'all', label: 'All scopes' },
            ...scopesOf(data ?? []).map((s) => ({ value: s, label: scopeLabel(s) })),
          ]}
        />
        <Select
          className="w-40"
          aria-label="Status"
          value={filter.status}
          onValueChange={(v) => setFilter((f) => ({ ...f, status: v as MemoryFilter['status'] }))}
          options={['all', 'proposed', 'active', 'stale', 'retired'].map((s) => ({
            value: s,
            label: s === 'all' ? 'All statuses' : s,
          }))}
        />
      </div>
      {isLoading && <SkeletonCard />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {data && entries.length === 0 && (
        <EmptyState icon={<Brain />} title="No memory matches" description="Change the filters." />
      )}
      {data && entries.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-[minmax(320px,420px)_1fr]">
          <motion.ul variants={staggerList()} initial="initial" animate="animate" className="space-y-2">
            {entries.map((e) => (
              <motion.li key={e.id} variants={listItem}>
                <button
                  type="button"
                  onClick={() => setParams({ entry: e.id })}
                  className={cn(
                    'w-full rounded-xl border bg-surface p-3 text-left transition-colors',
                    e.id === selectedId
                      ? 'border-primary shadow-glow'
                      : 'border-border hover:border-primary/40',
                  )}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-semibold">{e.id}</span>
                    <StatusPill status={e.status} tone={STATUS_TONE[e.status]} />
                    <Badge tone={e.scope === 'org' ? 'accent' : 'primary'}>{scopeLabel(e.scope)}</Badge>
                    <span className="ml-auto text-xs text-muted">used {e.usageCount}×</span>
                  </div>
                  <div className="mt-1 line-clamp-2 text-sm">{e.humanDecision}</div>
                  <div className="text-xs text-muted">
                    {e.reasonCategory} · {e.appliesTo.step ?? e.appliesTo.requirement ?? ''}
                  </div>
                </button>
              </motion.li>
            ))}
          </motion.ul>
          <Card className="h-fit p-5 lg:sticky lg:top-4">
            {selected ? (
              <MemoryDetail entry={selected} all={data} />
            ) : (
              <EmptyState compact title="Pick an entry" />
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
