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
  SkeletonCard,
} from '@/shared/ui';
import { useSystems } from '../hooks/useSystems';
import { RISK_META } from '../lib/styles';
import { SystemCard } from './SystemCard';

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <Card className="px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
      <AnimatedNumber value={value} className={`mt-1 block text-2xl font-semibold ${tone ?? ''}`} />
    </Card>
  );
}

export function SystemsGallery() {
  const { data, isLoading, error, refetch } = useSystems();
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
        icon={<Boxes />}
        title="AI systems"
        description="Every system in scope of the AI Act, with its dossier, plugins and audit status."
      />

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Systems" value={stats.total} />
        <Stat label="High risk" value={stats.high} tone="text-danger" />
        <Stat label="Awaiting approval" value={stats.awaiting} tone="text-warning" />
        <Stat label="Open gaps" value={stats.gaps} tone="text-primary" />
      </div>

      <div className="mb-5 flex flex-wrap items-center gap-3">
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
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 4 }, (_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
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
        <motion.div
          variants={staggerList()}
          initial="initial"
          animate="animate"
          className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
        >
          {systems.map((s) => (
            <SystemCard key={s.id} system={s} />
          ))}
        </motion.div>
      )}
    </div>
  );
}
