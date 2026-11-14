import { BookText, FolderTree, Puzzle, ScrollText } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { Badge, ErrorState, PageHeader, Skeleton, SkeletonText, StatusPill, Tabs } from '@/shared/ui';
import { ChatAboutButton } from '@/features/chat/components/ChatAboutButton';
import { useSystem } from '../hooks/useSystems';
import { SYSTEM_TABS, systemRoutes, type SystemTab } from '../lib/routes';
import { riskMeta } from '../lib/styles';
import { FolderTab } from './detail_parts/FolderTab';
import { OverviewTab } from './detail_parts/OverviewTab';
import { PluginsTab } from './detail_parts/PluginsTab';
import { RulesTab } from './detail_parts/RulesTab';

export function SystemDetail() {
  const { systemId = '', tab } = useParams();
  const navigate = useNavigate();
  const active: SystemTab = SYSTEM_TABS.includes(tab as SystemTab) ? (tab as SystemTab) : 'overview';
  const { data: system, isLoading, error, refetch } = useSystem(systemId);

  if (error) {
    return <ErrorState title={`Could not load ${systemId}`} error={error} onRetry={() => refetch()} />;
  }
  if (isLoading || !system) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <Skeleton className="size-11 rounded-xl" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-6 w-64" />
          </div>
        </div>
        <Skeleton className="h-10 w-96 rounded-lg" />
        <SkeletonText lines={6} />
      </div>
    );
  }

  const risk = riskMeta(system.data.risk_class);
  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: 'Systems', to: systemRoutes.list() }, { label: system.id }]}
        eyebrow={system.id}
        title={system.name}
        description={system.data.intended_purpose}
        meta={
          <>
            <Badge tone={risk.tone}>{risk.label}</Badge>
            {system.data.annex_basis && <Badge>{system.data.annex_basis}</Badge>}
            <StatusPill status={system.status} />
          </>
        }
        actions={<ChatAboutButton systemId={system.id} label="Chat about this system" />}
      />
      <Tabs value={active} onValueChange={(v) => navigate(systemRoutes.detail(system.id, v as SystemTab))}>
        <Tabs.List>
          <Tabs.Trigger value="overview">
            <BookText /> Overview
          </Tabs.Trigger>
          <Tabs.Trigger value="folder">
            <FolderTree /> Folder
          </Tabs.Trigger>
          <Tabs.Trigger value="plugins">
            <Puzzle /> Plugins
          </Tabs.Trigger>
          <Tabs.Trigger value="rules">
            <ScrollText /> Business rules
          </Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="overview">
          <OverviewTab system={system} />
        </Tabs.Content>
        <Tabs.Content value="folder">
          <FolderTab systemId={system.id} />
        </Tabs.Content>
        <Tabs.Content value="plugins">
          <PluginsTab systemId={system.id} />
        </Tabs.Content>
        <Tabs.Content value="rules">
          <RulesTab systemId={system.id} />
        </Tabs.Content>
      </Tabs>
    </div>
  );
}
