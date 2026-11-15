import { Search, X } from 'lucide-react';
import { Button, Input, Select } from '@/shared/ui';
import { SEVERITY } from '../../lib/findings';

export type FindingsGroup = 'none' | 'chapter' | 'verdict';

const GROUPS = [
  { value: 'none', label: 'No grouping' },
  { value: 'chapter', label: 'By chapter' },
  { value: 'verdict', label: 'By verdict' },
];

/** One compact row: search, severity, grouping, result count and a reset. */
export function FindingsToolbar({
  query,
  onQuery,
  severity,
  severities,
  onSeverity,
  group,
  onGroup,
  shown,
  total,
  filtered,
  onClear,
}: {
  query: string;
  onQuery: (q: string) => void;
  severity: string | null;
  severities: string[];
  onSeverity: (s: string | null) => void;
  group: FindingsGroup;
  onGroup: (g: FindingsGroup) => void;
  shown: number;
  total: number;
  filtered: boolean;
  onClear: () => void;
}) {
  const sevOptions = [
    { value: 'all', label: 'All severities' },
    ...severities.map((s) => ({
      value: s,
      label: s === 'none' ? 'No severity' : (SEVERITY[s as keyof typeof SEVERITY]?.label ?? s),
    })),
  ];
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="min-w-0 flex-[1_1_14rem]">
        <Input
          type="search"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder="Search article, obligation or text…"
          aria-label="Search findings"
          leftIcon={<Search />}
        />
      </div>
      <Select
        aria-label="Severity"
        value={severity ?? 'all'}
        onValueChange={(v) => onSeverity(v === 'all' ? null : v)}
        options={sevOptions}
        className="w-[9.5rem]"
      />
      <Select
        aria-label="Group"
        value={group}
        onValueChange={(v) => onGroup(v as FindingsGroup)}
        options={GROUPS}
        className="w-[9.5rem]"
      />
      <div className="ml-auto flex items-center gap-2 text-xs text-muted">
        <span className="num">{shown === total ? `${total} findings` : `${shown} of ${total}`}</span>
        {filtered && (
          <Button variant="ghost" size="sm" onClick={onClear} className="h-7 px-2">
            <X className="size-3.5" />
            Clear
          </Button>
        )}
      </div>
    </div>
  );
}
