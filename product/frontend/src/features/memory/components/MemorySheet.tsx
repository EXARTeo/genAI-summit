import { useMemoryLedger } from '../hooks/useMemory';
import { scopeLabel } from '../lib/memory';
import { useUiStore } from '@/shared/stores/ui';
import { EmptyState, Sheet, Skeleton } from '@/shared/ui';
import { MemoryDetail } from './MemoryDetail';

/** Global side sheet for one memory entry, opened from any "applied MEM-…" chip. */
export function MemorySheet() {
  const id = useUiStore((s) => s.memoryEntryId);
  const close = useUiStore((s) => s.openMemory);
  const { data, isLoading } = useMemoryLedger();
  const entry = data?.find((e) => e.id === id);
  return (
    <Sheet
      open={id != null}
      onOpenChange={(o) => !o && close(null)}
      title={id ? `Lesson ${id}` : 'Lesson'}
      description={entry ? `${scopeLabel(entry.scope)} memory the agent applied` : undefined}
      width="w-[min(34rem,100vw)]"
    >
      <div>
        {isLoading && <Skeleton className="h-64" />}
        {entry && <MemoryDetail entry={entry} all={data!} compact />}
        {data && !entry && (
          <EmptyState compact title="Entry not found" description="It may have been retired." />
        )}
      </div>
    </Sheet>
  );
}
