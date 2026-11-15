import {
  ArrowUpRight,
  CircleCheck,
  CircleDot,
  Lock,
  RotateCcw,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { actorLabel, formatStarted } from '@/shared/lib/labels';
import { Button, Timeline, type TimelineItem } from '@/shared/ui';
import { VerdictPill } from '@/features/audits/components/artifact_parts/common';
import { severityMeta } from '@/features/audits/lib/findings';
import { verdictStyle } from '@/features/audits/lib/styling';
import { useCloseRegisterItem, useReopenRegisterItem } from '../../hooks/useRegister';
import { eventLabel, eventTone, itemArticle, itemChapter } from '../../lib/register';
import type { RegisterEvent, RegisterItem } from '../../lib/types';
import { ReasonDialog } from './ReasonDialog';
import { StatePill } from './StatePill';

const auditHref = (id: string) => `/audits/${encodeURIComponent(id)}?view=findings`;

function AuditLink({ id }: { id: string }) {
  return (
    <Link
      to={auditHref(id)}
      className="num inline-flex items-center gap-0.5 font-mono text-xs text-primary hover:underline"
    >
      {id}
      <ArrowUpRight className="size-3" />
    </Link>
  );
}

function eventIcon(e: RegisterEvent): ReactNode {
  if (e.kind === 'resolved') return <CircleCheck />;
  if (e.kind === 'closed') return <ShieldCheck />;
  if (e.kind === 'reopened' || e.kind === 'regressed') return <RotateCcw />;
  if (e.to === 'open') return <TriangleAlert />;
  return <CircleDot />;
}

/** "gap -> pass" notes read as labels ("Gap → Pass"); a person's reason stays as written. */
function eventNote(e: RegisterEvent): string | undefined {
  if (!e.note) return undefined;
  const m = /^([a-z_]+) -> ([a-z_]+)$/.exec(e.note);
  return m ? `${verdictStyle(m[1]).label} → ${verdictStyle(m[2]).label}` : e.note;
}

function toTimeline(history: RegisterEvent[]): TimelineItem[] {
  return [...history].reverse().map((e, i) => ({
    id: `${e.at}-${i}`,
    at: e.at || undefined,
    tone: eventTone(e),
    icon: eventIcon(e),
    title: (
      <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
        {eventLabel(e)}
        {e.verdict && <span className="text-xs font-normal text-muted">{verdictStyle(e.verdict).label}</span>}
      </span>
    ),
    actor: e.audit_id ? undefined : actorLabel(e.actor),
    description: eventNote(e),
    content: e.audit_id ? <AuditLink id={e.audit_id} /> : undefined,
  }));
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-2xs font-medium uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-0.5 min-w-0 text-sm">{children}</dd>
    </div>
  );
}

/** One register item: what it is, where it stands, and its history (each audit linked). */
export function RegisterDetail({ item }: { item: RegisterItem }) {
  const [dialog, setDialog] = useState<'close' | 'reopen' | null>(null);
  const close = useCloseRegisterItem(item.system_id);
  const reopen = useReopenRegisterItem(item.system_id);
  const label = `${itemArticle(item)} · ${item.title ?? item.obligation_id}`;
  const sev = severityMeta(item.severity);

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <p className="text-2xs font-medium uppercase tracking-wide text-muted">
          {itemChapter(item)} · {itemArticle(item)}
        </p>
        <h3 className="text-base font-semibold leading-snug">{item.title ?? item.obligation_id}</h3>
        <div className="flex flex-wrap items-center gap-2">
          <StatePill item={item} />
          <VerdictPill verdict={item.verdict} />
          {sev && <span className="text-xs text-muted">{sev.label} severity</span>}
          {item.gap_id && <span className="num font-mono text-xs text-muted">{item.gap_id}</span>}
        </div>
      </div>

      <dl className="grid gap-x-4 gap-y-3 sm:grid-cols-2">
        <Fact label="First seen">
          <AuditLink id={item.first_seen_audit_id} />
        </Fact>
        <Fact label="Last seen">
          <AuditLink id={item.last_seen_audit_id} />
        </Fact>
        {item.state === 'open' && item.opened_at && (
          <Fact label="Open since">{formatStarted(item.opened_at)}</Fact>
        )}
        <Fact label="Audits">{new Set(item.history.map((e) => e.audit_id).filter(Boolean)).size}</Fact>
      </dl>

      {item.state === 'closed' && item.close_reason && (
        <div className="rounded-xl border border-info/25 bg-info/5 p-3">
          <p className="flex items-center gap-1.5 text-xs font-medium text-info">
            <Lock className="size-3.5" /> Accepted risk · {actorLabel(item.closed_by)}
            {item.closed_at && (
              <span className="font-normal text-muted">· {formatStarted(item.closed_at)}</span>
            )}
          </p>
          <p className="mt-1 text-sm">{item.close_reason}</p>
        </div>
      )}

      {item.last_reasoning && (
        <div>
          <p className="text-2xs font-medium uppercase tracking-wide text-muted">Last audit said</p>
          <p className="mt-1 text-sm text-text/85">{item.last_reasoning}</p>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {item.state !== 'closed' && item.state !== 'resolved' && (
          <Button size="sm" variant="secondary" leftIcon={<ShieldCheck />} onClick={() => setDialog('close')}>
            Close with reason
          </Button>
        )}
        {item.state !== 'open' && (
          <Button size="sm" variant="secondary" leftIcon={<RotateCcw />} onClick={() => setDialog('reopen')}>
            Reopen
          </Button>
        )}
      </div>

      <div>
        <p className="mb-3 text-2xs font-medium uppercase tracking-wide text-muted">History</p>
        <Timeline items={toTimeline(item.history)} />
      </div>

      <ReasonDialog
        open={dialog != null}
        onOpenChange={(o) => !o && setDialog(null)}
        mode={dialog ?? 'close'}
        label={label}
        onSubmit={(reason) =>
          dialog === 'reopen'
            ? reopen.mutateAsync({ obligationId: item.obligation_id, reason })
            : close.mutateAsync({ obligationId: item.obligation_id, reason })
        }
      />
    </div>
  );
}
