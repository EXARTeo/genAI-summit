import { motion } from 'framer-motion';
import { Boxes, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { staggerList } from '@/shared/lib/motion';
import {
  AnimatedNumber,
  Card,
  EmptyState,
  ErrorState,
  Input,
  PageHeader,
  Select,
  Skeleton,
} from '@/shared/ui';
import { useAudits } from '@/features/audits/hooks/useAudits';
import { useSystems } from '../hooks/useSystems';
import { withLastAudits } from '../lib/adapters';
import { RISK_META } from '../lib/styles';
import { SystemCard, SystemTableHeader } from './SystemCard';

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="px-4 py-3">
      <div className="text-xs text-muted">{label}</div>
      <AnimatedNumber value={value} className={`num mt-0.5 block text-2xl font-semibold ${tone ?? ''}`} />
    </div>
  );
}

export function SystemsGallery() {
  const { data: raw, isLoading, error, refetch } = useSystems();
  const { data: audits } = useAudits();
  const data = useMemo(() => (raw ? withLastAudits(raw, audits ?? []) : raw), [raw, audits]);
  const [q, setQ] = useState('');
  const [risk, setRisk] = useState('all');

  const systems = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data ?? []).filter(
      (s) =>
        (risk === 'all' || s.data.risk_class === risk) &&
        (!needle || `${s.id} ${s.name} ${s.data.organisation ?? ''}`.toLowerCase().includes(needle)),
    );
  }, [data, q, risk]);

  const all = data ?? [];
  const stats = {
    total: all.length,
    high: all.filter((s) => s.data.risk_class === 'high_risk').length,
    awaiting: all.filter((s) => s.data.last_audit?.status === 'awaiting_approval').length,
    gaps: all.reduce((n, s) => n + (s.data.last_audit?.findings?.gaps ?? 0), 0),
  };

  return (
    <div>
      <PageHeader
        title="AI systems"
        description="Every system in scope of the AI Act, with its dossier, plugins and audit status."
      />

      <Card className="mb-6 grid grid-cols-2 divide-border lg:grid-cols-4 lg:divide-x">
        <Stat label="Systems" value={stats.total} />
        <Stat label="High risk" value={stats.high} />
        <Stat label="Awaiting approval" value={stats.awaiting} tone={stats.awaiting ? 'text-warning' : ''} />
        <Stat label="Open gaps" value={stats.gaps} tone={stats.gaps ? 'text-danger' : ''} />
      </Card>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="w-full max-w-xs">
          <Input
            leftIcon={<Search />}
            placeholder="Filter by id, name, organisation"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label="Filter systems"
          />
        </div>
        <div className="w-44">
          <Select
            aria-label="Risk class"
            value={risk}
            onValueChange={setRisk}
            options={[
              { value: 'all', label: 'All risk classes' },
              ...Object.entries(RISK_META).map(([value, m]) => ({ value, label: m.label })),
            ]}
          />
        </div>
      </div>

      {error ? (
        <ErrorState title="Could not load systems" error={error} onRetry={() => refetch()} />
      ) : isLoading ? (
        <Card className="divide-y divide-border">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="flex items-center gap-4 px-4 py-4">
              <div className="flex-1 space-y-1.5">
                <Skeleton className="h-3.5 w-48" />
                <Skeleton className="h-3 w-72" />
              </div>
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-3 w-32" />
            </div>
          ))}
        </Card>
      ) : systems.length === 0 ? (
        <EmptyState
          icon={<Boxes />}
          title={all.length ? 'No system matches the filter' : 'No systems yet'}
          description={
            all.length
              ? 'Clear the search or pick another risk class.'
              : 'Seed the demo systems (SYS-001..004) through the backend, or register one.'
          }
        />
      ) : (
        <Card className="overflow-hidden">
          <SystemTableHeader />
          <motion.ul variants={staggerList()} initial="initial" animate="animate">
            {systems.map((s) => (
              <SystemCard key={s.id} system={s} />
            ))}
          </motion.ul>
        </Card>
      )}
    </div>
  );
}
