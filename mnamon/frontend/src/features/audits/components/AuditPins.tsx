import { Pin } from 'lucide-react';
import { cn } from '@/shared/lib/utils';
import { Tooltip } from '@/shared/ui';
import { auditCardVersion, auditKbVersion } from '../lib/adapters';
import type { Audit } from '../lib/types';

function show(v: unknown): string | null {
  if (v == null || v === '') return null;
  if (Array.isArray(v)) return v.join(', ');
  if (typeof v === 'object') return Object.values(v as Record<string, unknown>).join(', ');
  return String(v);
}

/** What the run pinned (plan 01 P3): kb, dossier, config and model versions, seeds. */
export function AuditPins({ audit, className }: { audit: Audit; className?: string }) {
  const p = audit.pins ?? {};
  const items: [string, string | null, string][] = [
    ['kb', show(p.kb_version) ?? auditKbVersion(audit) ?? null, 'Regulation knowledge-base version'],
    [
      'dossier',
      show(p.dossier_version) ?? (auditCardVersion(audit) != null ? String(auditCardVersion(audit)) : null),
      'System folder version',
    ],
    ['config', show(p.config_version), 'Target config version'],
    ['model', show(p.model_version) ?? show(p.model_uri), 'Model version resolved from the alias'],
    ['seeds', show(p.seeds), 'Random seeds'],
  ];
  const shown = items.filter(([, v]) => v != null);
  if (shown.length === 0) return null;
  return (
    <div className={cn('flex flex-wrap items-center gap-1.5', className)}>
      <Tooltip
        content={
          audit.pins ? 'Pinned at the start of the run; every read uses these.' : 'From the audit data'
        }
      >
        <span className="inline-flex items-center gap-1 text-2xs text-muted">
          <Pin className="size-3" /> Pinned
        </span>
      </Tooltip>
      {shown.map(([k, v, hint]) => (
        <Tooltip key={k} content={hint}>
          <span className="num inline-flex h-5 items-center gap-1 rounded-md border border-border bg-surface-muted/60 px-1.5 font-mono text-2xs">
            <span className="text-muted">{k}</span>
            <span className="max-w-[14rem] truncate text-text">{v}</span>
          </span>
        </Tooltip>
      ))}
    </div>
  );
}
