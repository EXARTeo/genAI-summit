import { ClipboardList, SearchX } from 'lucide-react';
import { useMemo, useState, type KeyboardEvent } from 'react';
import { Card, EmptyState, ErrorState, FilterBar, Skeleton, type Facet } from '@/shared/ui';
import { AI_ACT_CHAPTERS, SEVERITY, VERDICT_ORDER } from '@/features/audits/lib/findings';
import { TONE_CLASSES, verdictStyle } from '@/features/audits/lib/styling';
import { cn } from '@/shared/lib/utils';
import { useRegister } from '../hooks/useRegister';
import {
  STATE_KEYS,
  countBy,
  filterItems,
  itemChapter,
  sortItems,
  stateKey,
  stateKeyLabel,
  stateKeyTone,
} from '../lib/register';
import { RegisterDetail } from './register_parts/RegisterDetail';
import { RegisterRow } from './register_parts/RegisterRow';
import { RegisterSummary } from './register_parts/RegisterSummary';

const dot = (cls: string) => <span className={cn('size-2 rounded-full', cls)} />;

/**
 * The system's findings register ("Status" tab): its state now, per obligation, across every audit.
 * An open gap stays open until a person closes it with a reason or a later audit finds it fixed.
 */
export function RegisterTab({ systemId }: { systemId: string }) {
  const { data, isLoading, error, refetch } = useRegister(systemId);
  const [query, setQuery] = useState('');
  const [states, setStates] = useState<string[]>([]);
  const [verdicts, setVerdicts] = useState<string[]>([]);
  const [severities, setSeverities] = useState<string[]>([]);
  const [chapters, setChapters] = useState<string[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const items = useMemo(() => sortItems(data?.items ?? []), [data]);
  const visible = useMemo(
    () => filterItems(items, { query, states, verdicts, severities, chapters }),
    [items, query, states, verdicts, severities, chapters],
  );
  const selected =
    visible.find((i) => i.obligation_id === selectedId) ?? (selectedId === '' ? null : (visible[0] ?? null));

  const facets: Facet[] = useMemo(() => {
    const st = countBy(items, stateKey);
    const vd = countBy(items, (i) => i.verdict);
    const sv = countBy(items, (i) => i.severity ?? 'none');
    const ch = countBy(items, itemChapter);
    const chapterOrder = AI_ACT_CHAPTERS.map((c) => c.label).filter((c) => ch.has(c));
    return [
      {
        id: 'state',
        label: 'State',
        options: STATE_KEYS.filter((k) => st.has(k)).map((k) => ({
          value: k,
          label: stateKeyLabel(k),
          count: st.get(k),
          icon: dot(TONE_CLASSES[stateKeyTone(k)].dot),
        })),
        selected: states,
        onChange: setStates,
      },
      {
        id: 'verdict',
        label: 'Verdict',
        options: [...VERDICT_ORDER]
          .filter((v) => vd.has(v))
          .map((v) => ({
            value: v,
            label: verdictStyle(v).label,
            count: vd.get(v),
            icon: dot(TONE_CLASSES[verdictStyle(v).tone].dot),
          })),
        selected: verdicts,
        onChange: setVerdicts,
      },
      {
        id: 'severity',
        label: 'Severity',
        options: [...Object.keys(SEVERITY), 'none']
          .filter((s) => sv.has(s))
          .map((s) => ({
            value: s,
            label: s === 'none' ? 'No severity' : SEVERITY[s as keyof typeof SEVERITY].label,
            count: sv.get(s),
          })),
        selected: severities,
        onChange: setSeverities,
      },
      {
        id: 'chapter',
        label: 'Chapter',
        options: [...chapterOrder, ...(ch.has('Other') ? ['Other'] : [])].map((c) => ({
          value: c,
          label: c,
          count: ch.get(c),
        })),
        selected: chapters,
        onChange: setChapters,
      },
    ];
  }, [items, states, verdicts, severities, chapters]);

  if (error)
    return <ErrorState title="Could not load the register" error={error} onRetry={() => refetch()} />;
  if (isLoading || !data) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 rounded-xl" />
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-12 rounded-lg" />
        ))}
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <Card className="p-2">
        <EmptyState
          icon={<ClipboardList />}
          title="Nothing tracked yet"
          description="When an audit of this system finishes, every obligation it judged lands here and keeps its state across audits."
        />
      </Card>
    );
  }

  const toggleState = (k: string) =>
    setStates((cur) => (cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k]));
  const select = (id: string) =>
    setSelectedId((cur) => (cur === id || (cur == null && selected?.obligation_id === id) ? '' : id));
  const onListKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const i = selected ? visible.indexOf(selected) : -1;
    const next = visible[Math.min(visible.length - 1, Math.max(0, i + (e.key === 'ArrowDown' ? 1 : -1)))];
    if (!next) return;
    setSelectedId(next.obligation_id);
    e.currentTarget
      .querySelector<HTMLElement>(`[data-register-row="${CSS.escape(next.obligation_id)}"]`)
      ?.focus();
  };

  return (
    <div className="space-y-4">
      <RegisterSummary summary={data.summary} selected={states} onToggle={toggleState} />
      <FilterBar
        search={{ value: query, onChange: setQuery, placeholder: 'Search article, obligation, reason…' }}
        facets={facets}
        summary={
          visible.length === items.length
            ? `${items.length} obligations`
            : `${visible.length} of ${items.length}`
        }
      />
      {visible.length === 0 ? (
        <Card className="p-2">
          <EmptyState
            icon={<SearchX />}
            title="Nothing matches"
            description="Change the search or clear the filters."
          />
        </Card>
      ) : (
        <div className="xl:grid xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] xl:items-start xl:gap-4">
          <Card className="overflow-hidden" onKeyDown={onListKey}>
            <ul className="divide-y divide-border">
              {visible.map((item) => {
                const on = selected?.obligation_id === item.obligation_id;
                return (
                  <li key={item.obligation_id}>
                    <RegisterRow item={item} selected={on} onSelect={() => select(item.obligation_id)} />
                    {on && (
                      <div className="border-t border-border bg-surface-sunken/30 px-4 py-4 xl:hidden">
                        <RegisterDetail item={item} />
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </Card>
          <Card className="sticky top-4 hidden max-h-[calc(100vh-2rem)] overflow-y-auto p-5 xl:block">
            {selected ? (
              <RegisterDetail key={selected.obligation_id} item={selected} />
            ) : (
              <p className="py-10 text-center text-sm text-muted">Select an item to see its history.</p>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
