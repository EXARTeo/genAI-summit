import { ChevronRight, ShieldCheck } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { formatDateTime, formatRelative } from '@/shared/lib/format';
import { cn } from '@/shared/lib/utils';
import { Badge, StatusPill, type BadgeTone } from '@/shared/ui';
import { systemRoutes } from '../../lib/routes';
import { riskMeta } from '../../lib/styles';
import type { System } from '../../lib/types';

// Built here rather than on PageHeader: the system page needs a facts strip and the
// tab bar inside one framed header, which PageHeader's text-only layout does not cover.

const TILE: Partial<Record<BadgeTone, string>> = {
  danger: 'border-danger/25 bg-danger/10 text-danger',
  warning: 'border-warning/25 bg-warning/10 text-warning',
  success: 'border-success/25 bg-success/10 text-success',
};

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0 bg-surface px-5 py-3 sm:px-6">
      <dt className="text-2xs font-medium uppercase tracking-wider text-muted">{label}</dt>
      <dd className="mt-1 flex min-h-6 min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-sm">
        {children}
      </dd>
    </div>
  );
}

/** System page header: identity, actions, key facts and the tab bar (`tabs`). */
export function SystemHeader({
  system,
  actions,
  tabs,
}: {
  system: System;
  actions: ReactNode;
  tabs: ReactNode;
}) {
  const c = system.data;
  const risk = riskMeta(c.risk_class);
  const audit = c.last_audit;

  return (
    <header className="mb-2 overflow-hidden rounded-xl border border-border bg-surface shadow-card">
      <div className="p-5 sm:p-6">
        <nav aria-label="Breadcrumb" className="mb-4 flex items-center gap-1 text-xs text-muted">
          <Link to={systemRoutes.list()} className="transition-colors hover:text-text">
            Systems
          </Link>
          <ChevronRight className="size-3 opacity-60" />
          <span className="font-mono text-text/80">{system.id}</span>
        </nav>

        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-4">
            <span
              className={cn(
                'grid size-12 shrink-0 place-items-center rounded-xl border [&_svg]:size-6',
                TILE[risk.tone] ?? 'border-primary/25 bg-primary/10 text-primary',
              )}
              aria-hidden
            >
              <ShieldCheck />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{system.name}</h1>
                <StatusPill status={system.status} />
              </div>
              {c.organisation && <p className="mt-0.5 text-sm text-muted">{c.organisation}</p>}
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
        </div>

        {c.intended_purpose && (
          <p className="mt-4 max-w-3xl text-sm leading-relaxed text-muted">{c.intended_purpose}</p>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-px border-t border-border bg-border lg:grid-cols-4">
        <Fact label="Risk class">
          <Badge tone={risk.tone}>{risk.label}</Badge>
        </Fact>
        <Fact label="Legal basis">
          <span className="truncate font-mono text-xs" title={c.annex_basis}>
            {c.annex_basis ?? '—'}
          </span>
        </Fact>
        <Fact label="AI Act role">
          <span className="capitalize">{c.role ?? '—'}</span>
        </Fact>
        <Fact label="Last audit">
          {audit ? (
            <>
              <StatusPill status={audit.status} />
              <time dateTime={audit.at} title={formatDateTime(audit.at)} className="num text-xs text-muted">
                {formatRelative(audit.at)}
              </time>
            </>
          ) : (
            <span className="text-muted">Never audited</span>
          )}
        </Fact>
      </dl>

      <div className="border-t border-border">{tabs}</div>
    </header>
  );
}
