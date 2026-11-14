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
    <header className={cn('mb-6 space-y-3', className)}>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-xs text-muted">
          {breadcrumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <ChevronRight className="size-3" />}
              {c.to ? (
                <Link to={c.to} className="transition-colors hover:text-text">
                  {c.label}
                </Link>
              ) : (
                <span className="text-text">{c.label}</span>
              )}
            </span>
          ))}
        </nav>
      )}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          {icon && (
            <div className="grid size-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-primary to-accent text-white shadow-glow [&_svg]:size-5">
              {icon}
            </div>
          )}
          <div className="min-w-0">
            {eyebrow && (
              <div className="mb-0.5 font-mono text-xs font-medium uppercase tracking-wider text-accent">
                {eyebrow}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
              {meta}
            </div>
            {description && <p className="mt-1 max-w-3xl text-sm text-muted">{description}</p>}
          </div>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
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
            {title && <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">{title}</h2>}
            {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
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
        'grid gap-x-6 gap-y-4',
        columns === 1 && 'grid-cols-1',
        columns === 2 && 'grid-cols-1 sm:grid-cols-2',
        columns === 3 && 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3',
        className,
      )}
    >
      {items.map((it, i) => (
        <div key={i} className="min-w-0">
          <dt className="text-xs font-medium uppercase tracking-wide text-muted">{it.label}</dt>
          <dd className={cn('mt-1 break-words text-sm', it.mono && 'font-mono text-[13px]')}>
            {it.value ?? <span className="text-muted">-</span>}
          </dd>
          {it.hint && <dd className="mt-0.5 text-xs text-muted">{it.hint}</dd>}
        </div>
      ))}
    </dl>
  );
}
