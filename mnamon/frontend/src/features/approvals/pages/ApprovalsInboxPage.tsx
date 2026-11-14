import { AnimatePresence, motion } from 'framer-motion';
import { Hand, Inbox } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { formatRelative } from '@/shared/lib/format';
import { listItem } from '@/shared/lib/motion';
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton } from '@/shared/ui';
import { ApprovalDrawer } from '../components/ApprovalDrawer';
import { useOpenGates } from '../hooks/useApprovals';
import type { OpenGate } from '../lib/approvals';

const GATE_COPY: Record<string, string> = {
  scenarios: 'Approve the test plan before any data is generated.',
  datasets: 'Audit the synthetic data (spec, five gates, twin pairs) before any test runs.',
};

export function ApprovalsInboxPage() {
  const { gates, isLoading, error, refetch } = useOpenGates();
  const [active, setActive] = useState<OpenGate | null>(null);

  return (
    <div>
      <PageHeader
        title="Approvals"
        description="Human-in-the-loop gates: agents propose, you decide. Every decision is logged."
        meta={gates.length > 0 ? <Badge tone="warning">{gates.length} open</Badge> : undefined}
      />
      {isLoading && <Skeleton className="h-20 rounded-xl" />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {!isLoading && !error && gates.length === 0 && (
        <EmptyState
          icon={<Inbox />}
          title="Inbox zero"
          description="When an agent needs a decision it pauses and waits here for you."
          action={
            <Button asChild variant="secondary">
              <Link to="/audits">See audits</Link>
            </Button>
          }
        />
      )}
      {gates.length > 0 && (
        <Card className="overflow-hidden">
          <ul>
            <AnimatePresence initial={false}>
              {gates.map((g) => (
                <motion.li
                  key={`${g.auditId}-${g.gate}`}
                  variants={listItem}
                  initial="initial"
                  animate="animate"
                  exit={{ opacity: 0, height: 0, transition: { duration: 0.2 } }}
                  layout
                  className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-border px-4 py-4 last:border-b-0"
                >
                  <span className="approval-pulse grid size-8 shrink-0 place-items-center rounded-full bg-warning/15 text-warning">
                    <Hand className="size-4" />
                  </span>
                  <div className="min-w-0 flex-1 basis-56">
                    <div className="flex flex-wrap items-baseline gap-x-2">
                      <span className="text-sm font-medium">{g.label}</span>
                      <span className="text-sm text-muted">
                        {g.systemName} · {g.auditTitle}
                      </span>
                    </div>
                    <div className="mt-0.5 text-xs text-muted">
                      {GATE_COPY[g.gate] ?? 'A decision is needed.'}{' '}
                      <span className="num">Waiting {formatRelative(g.waitingSince)}.</span>
                    </div>
                  </div>
                  <div className="ml-auto flex items-center gap-2">
                    <Button asChild variant="ghost" size="sm">
                      <Link to={`/audits/${encodeURIComponent(g.auditId)}`}>Open run</Link>
                    </Button>
                    <Button variant="warning" size="sm" onClick={() => setActive(g)}>
                      Review & decide
                    </Button>
                  </div>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        </Card>
      )}
      <ApprovalDrawer
        auditId={active?.auditId ?? null}
        gate={active?.gate ?? null}
        open={!!active}
        onOpenChange={(o) => !o && setActive(null)}
      />
    </div>
  );
}
