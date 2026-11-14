import { motion } from 'framer-motion';
import { ArrowUpRight, Building2, Layers, ShieldAlert } from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatRelative } from '@/shared/lib/format';
import { listItem } from '@/shared/lib/motion';
import { AgentThinking, Badge, Card, StatusPill } from '@/shared/ui';
import { systemRoutes } from '../lib/routes';
import { riskMeta } from '../lib/styles';
import type { System } from '../lib/types';

export function SystemCard({ system }: { system: System }) {
  const card = system.data;
  const risk = riskMeta(card.risk_class);
  const audit = card.last_audit;
  return (
    <motion.div variants={listItem} className="h-full">
      <Link
        to={systemRoutes.detail(system.id)}
        className="group block h-full rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Card interactive className="flex h-full flex-col">
          <div className="flex items-start gap-3 p-5 pb-3">
            <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-primary/15 to-accent/15 text-primary">
              <ShieldAlert className="size-5" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="font-mono text-[11px] font-medium tracking-wider text-accent">{system.id}</div>
              <h3 className="truncate text-[15px] font-semibold leading-tight">{system.name}</h3>
            </div>
            <ArrowUpRight className="size-4 text-muted opacity-0 transition-all group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:opacity-100" />
          </div>
          <p className="line-clamp-2 px-5 text-sm text-muted">
            {card.intended_purpose ?? 'No intended purpose recorded.'}
          </p>
          <div className="flex flex-wrap gap-1.5 px-5 pt-3">
            <Badge tone={risk.tone}>{risk.label}</Badge>
            {card.annex_basis && <Badge>{card.annex_basis}</Badge>}
            {card.role && <Badge tone="primary">{card.role}</Badge>}
            {card.deployment?.status && <StatusPill status={card.deployment.status} />}
          </div>
          <div className="mt-auto flex items-center gap-3 border-t border-border px-5 py-3 text-xs text-muted">
            {audit?.status === 'running' ? (
              <AgentThinking size="sm" label="Audit running" detail={audit.id} />
            ) : audit ? (
              <>
                <StatusPill status={audit.status} />
                <span className="truncate">
                  {audit.id} · {formatRelative(audit.at)}
                </span>
                {audit.findings && audit.findings.gaps > 0 && (
                  <Badge tone="danger" className="ml-auto">
                    {audit.findings.gaps} gap{audit.findings.gaps === 1 ? '' : 's'}
                  </Badge>
                )}
              </>
            ) : (
              <span>Never audited</span>
            )}
          </div>
          <div className="flex items-center gap-4 border-t border-border bg-surface-muted/40 px-5 py-2 text-[11px] text-muted">
            <span className="flex min-w-0 items-center gap-1 truncate">
              <Building2 className="size-3 shrink-0" />
              {card.organisation ?? '-'}
            </span>
            <span className="ml-auto flex shrink-0 items-center gap-1">
              <Layers className="size-3" />
              {card.components?.length ?? 0} components
            </span>
          </div>
        </Card>
      </Link>
    </motion.div>
  );
}
