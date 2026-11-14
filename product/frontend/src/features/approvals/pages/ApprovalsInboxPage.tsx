import { AnimatePresence, motion } from 'framer-motion';
import { ArrowRight, Hand, Inbox } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { formatRelative } from '@/shared/lib/format';
import { listItem } from '@/shared/lib/motion';
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, SkeletonCard } from '@/shared/ui';
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
        description="Human-in-the-loop gates: agents propose, you approve. Every decision is logged and can become memory."
        icon={<Inbox />}
        meta={gates.length > 0 ? <Badge tone="warning">{gates.length} open</Badge> : undefined}
      />
      {isLoading && <SkeletonCard />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {!isLoading && !error && gates.length === 0 && (
        <EmptyState
          icon={<Inbox />}
          title="Inbox zero"
          description="When an agent needs a decision it waits here for you."
        />
      )}
      <div className="grid gap-3">
        <AnimatePresence initial={false}>
          {gates.map((g) => (
            <motion.div
              key={`${g.auditId}-${g.gate}`}
              variants={listItem}
              initial="initial"
              animate="animate"
              exit={{ opacity: 0, x: 40, transition: { duration: 0.25 } }}
              layout
            >
              <Card className="approval-pulse flex flex-wrap items-center gap-4 border-warning/40 p-4">
                <span className="grid size-10 place-items-center rounded-full bg-warning/15 text-warning">
                  <Hand className="size-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{g.label}</span>
                    <span className="font-mono text-xs text-muted">{g.systemId}</span>
                    <span className="text-sm">{g.systemName}</span>
                    <span className="text-sm text-muted">· {g.auditTitle}</span>
                  </div>
                  <div className="text-sm text-muted">{GATE_COPY[g.gate] ?? 'A decision is needed.'}</div>
                  <div className="text-xs text-muted">waiting {formatRelative(g.waitingSince)}</div>
                </div>
                <Link
                  to={`/audits/${encodeURIComponent(g.auditId)}`}
                  className="text-sm text-primary hover:underline"
                >
                  Open run
                </Link>
                <Button variant="warning" rightIcon={<ArrowRight />} onClick={() => setActive(g)}>
                  Review
                </Button>
              </Card>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
      <ApprovalDrawer
        auditId={active?.auditId ?? null}
        gate={active?.gate ?? null}
        open={!!active}
        onOpenChange={(o) => !o && setActive(null)}
      />
    </div>
  );
}
