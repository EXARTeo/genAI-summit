import { ChevronRight } from 'lucide-react';
import type { HTMLAttributes, ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { cn } from '@/shared/lib/utils';

export interface Crumb {
  label: ReactNode;
  to?: string;
}

export interface PageHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  /** Small label above the title (e.g. an id). */
  eyebrow?: ReactNode;
  breadcrumbs?: Crumb[];
  actions?: ReactNode;
  /** Badges etc. next to the title. */
  meta?: ReactNode;
  icon?: ReactNode;
  className?: string;
}

export function PageHeader({
  title,
  description,
  eyebrow,
  breadcrumbs,
  actions,
  meta,
  icon,
  className,
}: PageHeaderProps) {
  return (
    <header className={cn('mb-6', className)}>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="mb-2 flex items-center gap-1 text-xs text-muted">
          {breadcrumbs.map((c, i) => (
            <span key={i} className="flex min-w-0 items-center gap-1">
              {i > 0 && <ChevronRight className="size-3 shrink-0 opacity-60" />}
              {c.to ? (
                <Link to={c.to} className="truncate transition-colors hover:text-text">
                  {c.label}
                </Link>
              ) : (
                <span className="truncate text-text/80">{c.label}</span>
              )}
            </span>
          ))}
        </nav>
      )}
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="flex min-w-0 items-start gap-3">
          {icon && (
            <div className="mt-0.5 hidden size-8 shrink-0 place-items-center rounded-lg border border-border bg-surface text-muted sm:grid [&_svg]:size-4">
              {icon}
            </div>
          )}
          <div className="min-w-0">
            {eyebrow && <div className="mb-0.5 font-mono text-2xs text-muted">{eyebrow}</div>}
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
              {meta}
            </div>
            {description && <p className="mt-1 max-w-2xl text-sm text-muted">{description}</p>}
          </div>
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

export interface SectionProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}

export function Section({ title, description, actions, className, children, ...props }: SectionProps) {
  return (
    <section className={cn('space-y-3', className)} {...props}>
      {(title || actions) && (
        <div className="flex items-end justify-between gap-3">
          <div>
            {title && <h2 className="text-sm font-semibold">{title}</h2>}
            {description && <p className="text-xs text-muted">{description}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export interface KeyValueItem {
  label: ReactNode;
  value: ReactNode;
  /** Render the value in mono (ids, versions, URIs). */
  mono?: boolean;
  hint?: ReactNode;
}

export interface KeyValueProps {
  items: KeyValueItem[];
  columns?: 1 | 2 | 3;
  className?: string;
}

export function KeyValue({ items, columns = 2, className }: KeyValueProps) {
  return (
    <dl
      className={cn(
        'grid gap-x-6 gap-y-3',
        columns === 1 && 'grid-cols-1',
        columns === 2 && 'grid-cols-1 sm:grid-cols-2',
        columns === 3 && 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3',
        className,
      )}
    >
      {items.map((it, i) => (
        <div key={i} className="min-w-0">
          <dt className="text-xs text-muted">{it.label}</dt>
          <dd className={cn('mt-0.5 break-words text-sm', it.mono && 'num font-mono text-xs')}>
            {it.value ?? <span className="text-muted">-</span>}
          </dd>
          {it.hint && <dd className="mt-0.5 text-xs text-muted">{it.hint}</dd>}
        </div>
      ))}
    </dl>
  );
}
