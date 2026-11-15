// Built on Radix DropdownMenu (CheckboxItem keeps the menu open while picking several values);
// no shadcn "faceted filter" copy exists in this project, so this is the app's own version.
import * as Menu from '@radix-ui/react-dropdown-menu';
import { Check, ChevronDown, Search, SlidersHorizontal, X } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';

export interface FacetOption {
  value: string;
  label: ReactNode;
  /** How many rows have it (shown right-aligned in the menu). */
  count?: number;
  /** A small leading mark, e.g. a status dot (`<span className="size-2 rounded-full bg-success" />`). */
  icon?: ReactNode;
}

export interface Facet {
  id: string;
  label: string;
  icon?: ReactNode;
  options: FacetOption[];
  selected: string[];
  onChange: (values: string[]) => void;
}

/** One filter pill: label (+ how many picked) → a menu of checkable options with counts. */
function FacetPill({ facet }: { facet: Facet }) {
  const { selected, options } = facet;
  const picked = options.filter((o) => selected.includes(o.value));
  const toggle = (v: string) =>
    facet.onChange(selected.includes(v) ? selected.filter((s) => s !== v) : [...selected, v]);
  return (
    <Menu.Root>
      <Menu.Trigger asChild>
        <button
          type="button"
          className={cn(
            'inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-3.5',
            picked.length
              ? 'border-primary/40 bg-primary/10 text-primary'
              : 'border-border bg-surface text-text/85 hover:bg-surface-muted',
          )}
        >
          {facet.icon}
          {facet.label}
          {picked.length > 0 && (
            <span className="num rounded-full bg-primary px-1.5 text-[10px] font-semibold leading-4 text-primary-foreground">
              {picked.length}
            </span>
          )}
          <ChevronDown className="opacity-60" />
        </button>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content
          align="start"
          sideOffset={6}
          className="z-50 max-h-80 min-w-[13rem] overflow-y-auto rounded-xl border border-border bg-surface p-1 text-text shadow-lift data-[state=open]:animate-[fade-in_160ms_ease-out]"
        >
          <Menu.Label className="px-2 pb-1 pt-1.5 text-[11px] font-medium uppercase tracking-wider text-muted">
            {facet.label}
          </Menu.Label>
          {options.map((o) => {
            const on = selected.includes(o.value);
            return (
              <Menu.CheckboxItem
                key={o.value}
                checked={on}
                onSelect={(e) => {
                  e.preventDefault();
                  toggle(o.value);
                }}
                className="flex cursor-default select-none items-center gap-2 rounded-lg px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-surface-muted"
              >
                <span
                  className={cn(
                    'grid size-4 shrink-0 place-items-center rounded border',
                    on ? 'border-primary bg-primary text-primary-foreground' : 'border-border',
                  )}
                >
                  {on && <Check className="size-3" strokeWidth={3} />}
                </span>
                {o.icon}
                <span className="min-w-0 flex-1 truncate">{o.label}</span>
                {o.count != null && <span className="num text-xs text-muted">{o.count}</span>}
              </Menu.CheckboxItem>
            );
          })}
          {selected.length > 0 && (
            <>
              <Menu.Separator className="my-1 h-px bg-border" />
              <Menu.Item
                onSelect={() => facet.onChange([])}
                className="flex cursor-default items-center justify-center rounded-lg px-2 py-1.5 text-xs text-muted outline-none data-[highlighted]:bg-surface-muted data-[highlighted]:text-text"
              >
                Clear {facet.label.toLowerCase()}
              </Menu.Item>
            </>
          )}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}

export interface FilterBarProps {
  search?: { value: string; onChange: (v: string) => void; placeholder?: string };
  facets?: Facet[];
  /** e.g. "12 of 15 audits". */
  summary?: ReactNode;
  /** Extra controls on the right (sort, view switch). */
  end?: ReactNode;
  className?: string;
}

/**
 * The app's filter bar: a search field, filter pills (each a menu of checkable values with
 * counts), the active values as removable tags, "Clear all" and a live result count.
 */
export function FilterBar({ search, facets = [], summary, end, className }: FilterBarProps) {
  const active = facets.flatMap((f) =>
    f.selected.map((v) => ({ facet: f, value: v, option: f.options.find((o) => o.value === v) })),
  );
  const anyActive = active.length > 0 || !!search?.value;
  const clearAll = () => {
    search?.onChange('');
    facets.forEach((f) => f.selected.length && f.onChange([]));
  };
  return (
    <div
      className={cn('rounded-2xl border border-border bg-surface/70 p-2 shadow-sm backdrop-blur', className)}
    >
      <div className="flex flex-wrap items-center gap-2">
        {search && (
          <label className="relative flex h-8 min-w-[12rem] flex-1 items-center">
            <Search className="pointer-events-none absolute left-3 size-3.5 text-muted" />
            <input
              value={search.value}
              onChange={(e) => search.onChange(e.target.value)}
              placeholder={search.placeholder ?? 'Search…'}
              className="h-8 w-full rounded-full border border-transparent bg-surface-muted pl-8 pr-8 text-sm outline-none transition-colors placeholder:text-muted focus:border-primary/40 focus:bg-surface"
            />
            {search.value && (
              <button
                type="button"
                aria-label="Clear search"
                onClick={() => search.onChange('')}
                className="absolute right-2 grid size-5 place-items-center rounded-full text-muted hover:bg-surface-muted hover:text-text"
              >
                <X className="size-3" />
              </button>
            )}
          </label>
        )}
        {facets.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <SlidersHorizontal className="mx-1 size-3.5 text-muted" aria-hidden />
            {facets.map((f) => (
              <FacetPill key={f.id} facet={f} />
            ))}
          </div>
        )}
        {(summary || end) && (
          <div className="ml-auto flex items-center gap-2 pl-1">
            {summary && <span className="num whitespace-nowrap text-xs text-muted">{summary}</span>}
            {end}
          </div>
        )}
      </div>
      {anyActive && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-border/60 px-1 pt-2">
          {active.map(({ facet, value, option }) => (
            <span
              key={`${facet.id}:${value}`}
              className="inline-flex items-center gap-1.5 rounded-full bg-surface-muted py-0.5 pl-2.5 pr-1 text-xs"
            >
              <span className="text-muted">{facet.label}:</span>
              {option?.icon}
              <span className="font-medium">{option?.label ?? value}</span>
              <button
                type="button"
                aria-label={`Remove ${facet.label} filter`}
                onClick={() => facet.onChange(facet.selected.filter((s) => s !== value))}
                className="grid size-4 place-items-center rounded-full text-muted hover:bg-surface hover:text-text"
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
          <button
            type="button"
            onClick={clearAll}
            className="ml-1 text-xs font-medium text-primary hover:underline"
          >
            Clear all
          </button>
        </div>
      )}
    </div>
  );
}
