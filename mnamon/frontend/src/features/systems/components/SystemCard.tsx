import { motion } from 'framer-motion';
import { ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatRelative } from '@/shared/lib/format';
import { listItem } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';
import { AgentThinking, StatusPill } from '@/shared/ui';
import { systemRoutes } from '../lib/routes';
import { riskMeta } from '../lib/styles';
import type { System } from '../lib/types';

/** Grid template shared by the header and every row (md and up). */
export const SYSTEM_GRID = 'md:grid-cols-[minmax(0,2.2fr)_120px_110px_minmax(0,1.3fr)_80px_16px]';

/** Column headers for the systems table. */
export function SystemTableHeader() {
  return (
    <div
      className={cn(
        'hidden gap-4 border-b border-border px-4 py-2 text-2xs font-medium text-muted md:grid',
        SYSTEM_GRID,
      )}
    >
      <span>System</span>
      <span>Risk class</span>
      <span>Deployment</span>
      <span>Last audit</span>
      <span className="text-right">Gaps</span>
      <span />
    </div>
  );
}

/** One system as a table row (stacks on mobile). */
export function SystemCard({ system }: { system: System }) {
  const card = system.data;
  const risk = riskMeta(card.risk_class);
  const audit = card.last_audit;
  const gaps = audit?.findings?.gaps ?? 0;
  return (
    <motion.li variants={listItem} className="border-b border-border last:border-b-0">
      <Link
        to={systemRoutes.detail(system.id)}
        className={cn(
          'group grid grid-cols-1 items-center gap-x-4 gap-y-2 px-4 py-3.5 transition-colors hover:bg-surface-muted/50 focus-visible:bg-surface-muted/50 focus-visible:outline-none',
          SYSTEM_GRID,
        )}
      >
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="truncate text-sm font-medium">{system.name}</span>
            <span className="num shrink-0 font-mono text-2xs text-muted">{system.id}</span>
          </div>
          <div className="mt-0.5 truncate text-xs text-muted">
            {card.organisation ?? '-'}
            {card.role && ` · ${card.role}`}
            {card.annex_basis && ` · ${card.annex_basis}`}
          </div>
        </div>
        <div className="hidden text-xs md:block">
          <span className="inline-flex items-center gap-1.5">
            <span
              className={cn(
                'size-1.5 rounded-full',
                risk.tone === 'danger' ? 'bg-danger' : risk.tone === 'warning' ? 'bg-warning' : 'bg-muted',
              )}
            />
            {risk.label}
          </span>
        </div>
        <div className="hidden text-xs capitalize text-muted md:block">{card.deployment?.status ?? '-'}</div>
        <div className="min-w-0 text-xs text-muted">
          {audit?.status === 'running' ? (
            <AgentThinking size="sm" label="Audit running" />
          ) : audit ? (
            <span className="flex min-w-0 items-center gap-2">
              <StatusPill status={audit.status} />
              <span className="num truncate">{formatRelative(audit.at)}</span>
              {gaps > 0 && (
                <span className="num ml-auto font-medium text-danger md:hidden">
                  {gaps} gap{gaps > 1 ? 's' : ''}
                </span>
              )}
            </span>
          ) : (
            <span>Never audited</span>
          )}
        </div>
        <div
          className={cn(
            'num hidden text-right text-sm md:block',
            gaps > 0 ? 'font-medium text-danger' : 'text-muted',
          )}
        >
          {audit?.findings ? gaps : '–'}
        </div>
        <ChevronRight className="hidden size-4 text-muted opacity-0 transition-opacity group-hover:opacity-100 md:block" />
      </Link>
    </motion.li>
  );
}
