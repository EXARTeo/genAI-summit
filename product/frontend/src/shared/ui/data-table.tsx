import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';
import { Skeleton } from './skeleton';
import { EmptyState } from './states';

export interface DataTableColumn<T> {
  id: string;
  header: ReactNode;
  /** Cell content; defaults to `String(row[id])`. */
  cell?: (row: T) => ReactNode;
  /** Value used for sorting; enables sorting when given (or when `sortable`). */
  sortValue?: (row: T) => string | number | null | undefined;
  sortable?: boolean;
  align?: 'left' | 'right' | 'center';
  width?: string;
  className?: string;
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  loading?: boolean;
  empty?: ReactNode;
  /** Height of the scroll area; the header sticks to its top. */
  maxHeight?: string;
  initialSort?: { id: string; dir: 'asc' | 'desc' };
  className?: string;
}

type Sort = { id: string; dir: 'asc' | 'desc' } | null;

/** Sortable table with a sticky header. Sorting is client-side. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  loading,
  empty,
  maxHeight = '36rem',
  initialSort,
  className,
}: DataTableProps<T>) {
  const [sort, setSort] = useState<Sort>(initialSort ?? null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.id === sort.id);
    if (!col) return rows;
    const get =
      col.sortValue ??
      ((r: T) => (r as Record<string, unknown>)[col.id] as string | number | null | undefined);
    const out = [...rows].sort((a, b) => {
      const va = get(a);
      const vb = get(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === 'number' && typeof vb === 'number') return va - vb;
      return String(va).localeCompare(String(vb), undefined, { numeric: true });
    });
    return sort.dir === 'desc' ? out.reverse() : out;
  }, [rows, sort, columns]);

  const toggle = (id: string) =>
    setSort((s) => (s?.id !== id ? { id, dir: 'asc' } : s.dir === 'asc' ? { id, dir: 'desc' } : null));

  return (
    <div className={cn('overflow-hidden rounded-xl border border-border bg-surface shadow-card', className)}>
      <div className="overflow-auto" style={{ maxHeight }}>
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-surface-muted/90 backdrop-blur">
            <tr>
              {columns.map((c) => {
                const canSort = c.sortable || !!c.sortValue;
                const active = sort?.id === c.id;
                return (
                  <th
                    key={c.id}
                    scope="col"
                    style={{ width: c.width }}
                    aria-sort={active ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : undefined}
                    className={cn(
                      'border-b border-border px-4 py-2 text-xs font-medium text-muted',
                      c.align === 'right' ? 'text-right' : c.align === 'center' ? 'text-center' : 'text-left',
                    )}
                  >
                    {canSort ? (
                      <button
                        type="button"
                        onClick={() => toggle(c.id)}
                        className={cn(
                          'inline-flex items-center gap-1 uppercase transition-colors hover:text-text',
                          active && 'text-text',
                        )}
                      >
                        {c.header}
                        {active ? (
                          sort!.dir === 'asc' ? (
                            <ArrowUp className="size-3" />
                          ) : (
                            <ArrowDown className="size-3" />
                          )
                        ) : (
                          <ChevronsUpDown className="size-3 opacity-50" />
                        )}
                      </button>
                    ) : (
                      c.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: 5 }, (_, i) => (
                  <tr key={i}>
                    {columns.map((c) => (
                      <td key={c.id} className="border-b border-border px-4 py-3">
                        <Skeleton className="h-3.5" />
                      </td>
                    ))}
                  </tr>
                ))
              : sorted.map((row) => (
                  <tr
                    key={rowKey(row)}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    className={cn(
                      'transition-colors last:[&>td]:border-b-0',
                      onRowClick && 'cursor-pointer hover:bg-primary/[0.04]',
                    )}
                  >
                    {columns.map((c) => (
                      <td
                        key={c.id}
                        className={cn(
                          'border-b border-border px-4 py-3 align-middle',
                          c.align === 'right'
                            ? 'text-right'
                            : c.align === 'center'
                              ? 'text-center'
                              : 'text-left',
                          c.className,
                        )}
                      >
                        {c.cell ? c.cell(row) : String((row as Record<string, unknown>)[c.id] ?? '')}
                      </td>
                    ))}
                  </tr>
                ))}
          </tbody>
        </table>
        {!loading && rows.length === 0 && (empty ?? <EmptyState compact title="Nothing here yet" />)}
      </div>
    </div>
  );
}
