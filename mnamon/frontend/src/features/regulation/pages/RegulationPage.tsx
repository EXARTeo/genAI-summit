import { motion } from 'framer-motion';
import { Landmark, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { staggerList } from '@/shared/lib/motion';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  Select,
  SkeletonCard,
  Tabs,
  toast,
} from '@/shared/ui';
import { RegChangeCard, SourceDetail, SourceRow } from '../components/RegViews';
import { useCheckNow, useRegChanges, useRegSources } from '../hooks/useRegulation';
import { latestVersion, openChanges } from '../lib/regulation';

export function RegulationPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') ?? 'changes';
  const sources = useRegSources();
  const checkNow = useCheckNow();
  const changes = useRegChanges();
  const [kind, setKind] = useState('all');
  const [version, setVersion] = useState<number | null>(null);

  const list = (sources.data ?? []).filter((s) => kind === 'all' || s.kind === kind);
  const selectedId = params.get('source') ?? list[0]?.id;
  const selected = sources.data?.find((s) => s.id === selectedId);
  const open = openChanges(changes.data ?? []);

  return (
    <div>
      <PageHeader
        title="Regulation"
        description="Every regulatory source the agents read, versioned with text and diffs; changes flow into an impact analysis per system."
        icon={<Landmark />}
        meta={
          open.length > 0 ? (
            <Badge tone="warning">
              {open.length} change{open.length > 1 ? 's' : ''} to review
            </Badge>
          ) : undefined
        }
        actions={
          <Button
            variant="secondary"
            loading={checkNow.isPending}
            onClick={() =>
              checkNow.mutate(undefined, {
                onSuccess: (r) =>
                  toast.success('Regulation check started', {
                    description: `Status: ${r?.status ?? 'queued'}. New changes appear in the inbox.`,
                  }),
                onError: (e) =>
                  toast.error('Could not start the check', { description: (e as Error).message }),
              })
            }
          >
            <RefreshCw /> Check now
          </Button>
        }
      />
      <Tabs value={tab} onValueChange={(t) => setParams({ tab: t })}>
        <Tabs.List>
          <Tabs.Trigger value="changes">Change inbox</Tabs.Trigger>
          <Tabs.Trigger value="sources">Sources</Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="changes">
          {changes.isLoading && <SkeletonCard />}
          {changes.error && <ErrorState error={changes.error} onRetry={() => void changes.refetch()} />}
          {changes.data?.length === 0 && <EmptyState icon={<Landmark />} title="No changes detected" />}
          <motion.div variants={staggerList(0.08)} initial="initial" animate="animate" className="space-y-3">
            {(changes.data ?? []).map((c) => (
              <RegChangeCard key={c.id} c={c} />
            ))}
          </motion.div>
        </Tabs.Content>

        <Tabs.Content value="sources">
          {sources.isLoading && <SkeletonCard />}
          {sources.error && <ErrorState error={sources.error} onRetry={() => void sources.refetch()} />}
          {sources.data && (
            <div className="grid gap-4 lg:grid-cols-[minmax(300px,400px)_1fr]">
              <div className="space-y-2">
                <Select
                  aria-label="Kind"
                  value={kind}
                  onValueChange={setKind}
                  options={[
                    { value: 'all', label: 'All kinds' },
                    ...Array.from(new Set(sources.data.map((s) => s.kind))).map((k) => ({
                      value: k,
                      label: k,
                    })),
                  ]}
                />
                {list.map((s) => (
                  <SourceRow
                    key={s.id}
                    s={s}
                    selected={s.id === selectedId}
                    onSelect={() => {
                      setVersion(null);
                      setParams({ tab: 'sources', source: s.id });
                    }}
                  />
                ))}
              </div>
              <Card className="h-fit min-w-0 p-5">
                {selected ? (
                  <SourceDetail
                    s={selected}
                    version={version ?? latestVersion(selected)}
                    onVersion={setVersion}
                  />
                ) : (
                  <EmptyState compact title="Pick a source" />
                )}
              </Card>
            </div>
          )}
        </Tabs.Content>
      </Tabs>
    </div>
  );
}
