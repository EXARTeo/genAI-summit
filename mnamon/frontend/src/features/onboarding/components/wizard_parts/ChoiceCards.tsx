import { Check } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';

export interface Choice<T extends string> {
  value: T;
  label: ReactNode;
  hint?: ReactNode;
}

/** A radio group drawn as selectable cards (native radios, so keyboard and screen readers work). */
export function ChoiceCards<T extends string>({
  name,
  label,
  value,
  onChange,
  options,
  error,
  hint,
  columns = 3,
}: {
  name: string;
  label: ReactNode;
  value: T | '';
  onChange: (v: T) => void;
  options: Choice<T>[];
  error?: string;
  hint?: ReactNode;
  columns?: 2 | 3;
}) {
  return (
    <fieldset className="space-y-1.5" aria-invalid={!!error || undefined}>
      <legend className="mb-1.5 text-sm font-medium">{label}</legend>
      <div className={cn('grid gap-2', columns === 3 ? 'sm:grid-cols-3' : 'sm:grid-cols-2')}>
        {options.map((o) => {
          const on = value === o.value;
          return (
            <label
              key={o.value}
              className={cn(
                'relative flex cursor-pointer flex-col gap-0.5 rounded-lg border px-3 py-2.5 text-sm transition-colors',
                'has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring/60',
                on
                  ? 'border-primary/60 bg-primary/[0.06]'
                  : error
                    ? 'border-danger/50 hover:bg-surface-muted/60'
                    : 'border-border hover:bg-surface-muted/60',
              )}
            >
              <input
                type="radio"
                name={name}
                value={o.value}
                checked={on}
                onChange={() => onChange(o.value)}
                className="sr-only"
              />
              <span className="flex items-center justify-between gap-2 font-medium">
                {o.label}
                <span
                  aria-hidden
                  className={cn(
                    'grid size-4 shrink-0 place-items-center rounded-full border [&_svg]:size-3',
                    on ? 'border-primary bg-primary text-primary-foreground' : 'border-border',
                  )}
                >
                  {on && <Check />}
                </span>
              </span>
              {o.hint && <span className="text-xs text-muted">{o.hint}</span>}
            </label>
          );
        })}
      </div>
      {error ? (
        <p className="text-xs text-danger">{error}</p>
      ) : hint ? (
        <p className="text-xs text-muted">{hint}</p>
      ) : null}
    </fieldset>
  );
}
