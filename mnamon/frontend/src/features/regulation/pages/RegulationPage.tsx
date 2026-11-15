import { useSearchParams } from 'react-router-dom';
import { EmptyState, ErrorState, PageHeader, Skeleton, Tabs } from '@/shared/ui';
import { ChangeInbox } from '../components/ChangeInbox';
import { SourcesGrid } from '../components/SourcesGrid';
import { useRegChanges, useRegSources } from '../hooks/useRegulation';
import { useUnread } from '../hooks/useSeen';

export function RegulationPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') === 'sources' ? 'sources' : 'changes';
  const sources = useRegSources();
  const changes = useRegChanges();
  const unread = useUnread(changes.data);

  return (
    <div>
      <PageHeader
        title="Regulation"
        description="Every source the agents read, versioned and decomposed per article. Changes arrive as diffs and flow into an impact judgement per system."
      />
      <Tabs value={tab} onValueChange={(t) => setParams({ tab: t })}>
        <Tabs.List>
          <Tabs.Trigger value="changes">
            Change inbox
            {unread.unreadCount > 0 && (
              <span className="rounded-full bg-primary px-1.5 text-2xs font-semibold tabular-nums text-primary-foreground">
                {unread.unreadCount}
              </span>
            )}
          </Tabs.Trigger>
          <Tabs.Trigger value="sources">
            Sources
            {sources.data && <span className="text-2xs tabular-nums text-muted">{sources.data.length}</span>}
          </Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="changes" className="mt-6">
          <ChangeInbox />
        </Tabs.Content>

        <Tabs.Content value="sources" className="mt-6">
          {sources.isLoading && (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-36" />
              ))}
            </div>
          )}
          {sources.error && <ErrorState error={sources.error} onRetry={() => void sources.refetch()} />}
          {sources.data?.length === 0 && <EmptyState title="No sources in the catalog" />}
          {sources.data && sources.data.length > 0 && <SourcesGrid sources={sources.data} />}
        </Tabs.Content>
      </Tabs>
    </div>
  );
}
