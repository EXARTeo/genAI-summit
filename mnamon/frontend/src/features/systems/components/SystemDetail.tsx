import { BookText, ClipboardList, FolderTree, ListChecks, Puzzle, ScrollText } from 'lucide-react';
import { useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ErrorState, Skeleton, SkeletonText, Tabs } from '@/shared/ui';
import { ChatAboutButton } from '@/features/chat/components/ChatAboutButton';
import { useAudits } from '@/features/audits/hooks/useAudits';
import { RegisterTab } from '@/features/register/components/RegisterTab';
import { useSystem } from '../hooks/useSystems';
import { withLastAudits } from '../lib/adapters';
import { SYSTEM_TABS, systemRoutes, type SystemTab } from '../lib/routes';
import { StartAuditButton } from './StartAuditButton';
import { FolderTab } from './detail_parts/FolderTab';
import { ObligationsTab } from './detail_parts/ObligationsTab';
import { OverviewTab } from './detail_parts/OverviewTab';
import { PluginsTab } from './detail_parts/PluginsTab';
import { RulesTab } from './detail_parts/RulesTab';
import { SystemHeader } from './detail_parts/SystemHeader';

// Underline tabs that sit in the header's bottom band.
const TAB_LIST = 'flex h-auto w-full justify-start gap-1 rounded-none bg-transparent p-0 px-3 sm:px-4';
const TAB =
  'relative h-11 rounded-none bg-transparent px-3 after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:rounded-full after:bg-transparent after:transition-colors data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:after:bg-primary [&_svg]:size-4';

export function SystemDetail() {
  const { systemId = '', tab } = useParams();
  const navigate = useNavigate();
  const active: SystemTab = SYSTEM_TABS.includes(tab as SystemTab) ? (tab as SystemTab) : 'overview';
  const { data: raw, isLoading, error, refetch } = useSystem(systemId);
  // The backend does not send `last_audit`; fill it from the audits list exactly as the
  // Systems list does, so the header and Overview agree with it.
  const { data: audits } = useAudits();
  const system = useMemo(() => (raw ? withLastAudits([raw], audits ?? [])[0] : raw), [raw, audits]);

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
        <Skeleton className="h-40 w-full rounded-xl" />
        <SkeletonText lines={6} />
      </div>
    );
  }

  return (
    <div>
      <Tabs value={active} onValueChange={(v) => navigate(systemRoutes.detail(system.id, v as SystemTab))}>
        <SystemHeader
          system={system}
          actions={
            <>
              <ChatAboutButton systemId={system.id} label="Chat" />
              <StartAuditButton systemId={system.id} systemName={system.name} />
            </>
          }
          tabs={
            <Tabs.List className={TAB_LIST}>
              <Tabs.Trigger value="overview" className={TAB}>
                <BookText /> Overview
              </Tabs.Trigger>
              <Tabs.Trigger value="status" className={TAB}>
                <ClipboardList /> Status
              </Tabs.Trigger>
              <Tabs.Trigger value="obligations" className={TAB}>
                <ListChecks /> Obligations
              </Tabs.Trigger>
              <Tabs.Trigger value="folder" className={TAB}>
                <FolderTree /> Folder
              </Tabs.Trigger>
              <Tabs.Trigger value="plugins" className={TAB}>
                <Puzzle /> Plugins
              </Tabs.Trigger>
              <Tabs.Trigger value="rules" className={TAB}>
                <ScrollText /> Business rules
              </Tabs.Trigger>
            </Tabs.List>
          }
        />
        <Tabs.Content value="overview">
          <OverviewTab system={system} />
        </Tabs.Content>
        <Tabs.Content value="status">
          <RegisterTab systemId={system.id} />
        </Tabs.Content>
        <Tabs.Content value="obligations">
          <ObligationsTab systemId={system.id} />
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
