import { Play } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button, DropdownMenu, toast } from '@/shared/ui';
import { useStartAudit, useSystems } from '../hooks/useSystems';

function useStart() {
  const navigate = useNavigate();
  const start = useStartAudit();
  const run = (systemId: string, systemName?: string) =>
    start.mutate(
      { systemId, systemName },
      {
        onSuccess: (audit) => {
          toast.success(`Audit started: ${systemName ?? systemId}`);
          navigate(`/audits/${encodeURIComponent(audit.id)}`);
        },
        onError: (e) => toast.error('Could not start the audit', { description: (e as Error).message }),
      },
    );
  return { run, pending: start.isPending };
}

/** Starts an audit of one system (POST /v1/systems/{id}/audits) and opens it. */
export function StartAuditButton({ systemId, systemName }: { systemId: string; systemName?: string }) {
  const { run, pending } = useStart();
  return (
    <Button onClick={() => run(systemId, systemName)} loading={pending}>
      <Play /> Start audit
    </Button>
  );
}

/** "Start audit" with a system picker, for pages without a system in context. */
export function StartAuditMenu() {
  const { data: systems = [] } = useSystems();
  const { run, pending } = useStart();
  return (
    <DropdownMenu
      trigger={
        <Button loading={pending} disabled={systems.length === 0}>
          <Play /> Start audit
        </Button>
      }
      items={[
        { type: 'label', label: 'Audit a system' },
        ...systems.map((s) => ({
          label: `${s.id} · ${s.name}`,
          onSelect: () => run(s.id, s.name),
        })),
      ]}
    />
  );
}
