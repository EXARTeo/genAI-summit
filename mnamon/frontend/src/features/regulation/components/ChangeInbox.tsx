import { CheckCheck, Inbox, RefreshCw } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { TONE_CLASSES } from '@/features/audits/lib/styling';
import { formatRelative } from '@/shared/lib/format';
import { cn } from '@/shared/lib/utils';
import { Button, EmptyState, ErrorState, Skeleton, toast } from '@/shared/ui';
import { useCheckNow, useRegChanges } from '../hooks/useRegulation';
import { useUnread } from '../hooks/useSeen';
import { seenStore } from '../lib/seen';
import { JUDGE, changeFiles, worstDecision } from '../lib/regulation';
import type { RegChange } from '../lib/types';
import { ChangeDetail } from './ChangeDetail';
import { SimulateChangeButton } from './SimulateChangeDialog';

/** The change inbox: a mail-style list of changes (unread first-class) beside the selected commit. */
export function ChangeInbox() {
  const [params, setParams] = useSearchParams();
  const changes = useRegChanges();
  const checkNow = useCheckNow();
  const list = changes.data ?? [];
  const unread = useUnread(list);
  const picked = params.get('change');
  const selected = list.find((c) => c.id === picked) ?? (picked ? undefined : list[0]);

  const select = (c: RegChange) => {
    seenStore.markChange(c.id);
    setParams({ tab: 'changes', change: c.id }, { replace: false });
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(280px,340px)_minmax(0,1fr)] lg:gap-8">
      <aside
        className={cn(
          'min-w-0 lg:sticky lg:top-[calc(var(--topbar-height)+1rem)] lg:self-start',
          picked && 'max-lg:hidden',
        )}
      >
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Inbox className="size-4 text-muted" />
          <h2 className="text-sm font-semibold">Inbox</h2>
          {unread.unreadCount > 0 ? (
            <span className="rounded-full bg-primary px-1.5 text-2xs font-semibold tabular-nums text-primary-foreground">
              {unread.unreadCount} new
            </span>
          ) : (
            list.length > 0 && <span className="text-2xs text-muted">all read</span>
          )}
          {unread.unreadCount > 0 && (
            <button
              type="button"
              onClick={() => seenStore.markAll(list.map((c) => c.id))}
              className="ml-auto inline-flex items-center gap-1 text-2xs text-muted hover:text-text"
            >
              <CheckCheck className="size-3.5" /> Mark all read
            </button>
          )}
        </div>
        <div className="mb-3 flex flex-wrap gap-2">
          <SimulateChangeButton />
          <Button
            variant="secondary"
            leftIcon={<RefreshCw />}
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
            Check now
          </Button>
        </div>
        {changes.isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        )}
        {changes.error && <ErrorState error={changes.error} onRetry={() => void changes.refetch()} />}
        {changes.data?.length === 0 && (
          <EmptyState
            compact
            icon={<Inbox />}
            title="No changes detected"
            description="Run Check now or simulate one."
          />
        )}
        {list.length > 0 && (
          <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
            {list.map((c) => (
              <ChangeRow
                key={c.id}
                c={c}
                active={c.id === selected?.id}
                isNew={unread.isNewChange(c)}
                newFiles={unread.newFiles(c)}
                onSelect={() => select(c)}
              />
            ))}
          </ul>
        )}
      </aside>

      <div className={cn('min-w-0', !picked && 'max-lg:hidden')}>
        {selected ? (
          <ChangeDetail c={selected} onBack={() => setParams({ tab: 'changes' })} />
        ) : changes.isLoading ? (
          <Skeleton className="h-64" />
        ) : changes.error ? (
          <ErrorState error={changes.error} onRetry={() => void changes.refetch()} />
        ) : (
          picked && (
            <EmptyState compact title="Change not found" description={`${picked} is not in the inbox.`} />
          )
        )}
      </div>
    </div>
  );
}

function ChangeRow({
  c,
  active,
  isNew,
  newFiles,
  onSelect,
}: {
  c: RegChange;
  active: boolean;
  isNew: boolean;
  newFiles: number;
  onSelect: () => void;
}) {
  const files = changeFiles(c).length;
  const worst = c.affected.length > 0 ? JUDGE[worstDecision(c)] : null;
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={active || undefined}
        className={cn(
          'relative flex w-full gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-hover',
          active && 'bg-surface-sunken/70',
        )}
      >
        {active && <span className="absolute inset-y-0 left-0 w-0.5 bg-primary" aria-hidden />}
        <span
          className={cn('mt-1.5 size-2 shrink-0 rounded-full', isNew ? 'bg-primary' : 'bg-transparent')}
          aria-label={isNew ? 'New' : undefined}
        />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span
              className={cn(
                'line-clamp-2 min-w-0 flex-1 text-sm leading-snug',
                isNew ? 'font-semibold text-text' : 'text-text/80',
              )}
            >
              {c.title}
            </span>
            <span className="shrink-0 text-2xs text-muted">{formatRelative(c.detectedAt)}</span>
          </span>
          <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-2xs text-muted">
            <span className="font-mono">{c.id}</span>
            <span>{c.changeType.replace(/_/g, ' ')}</span>
            <span className="tabular-nums">
              {files} file{files === 1 ? '' : 's'}
              {newFiles > 0 && newFiles < files && <span className="text-primary"> · {newFiles} new</span>}
            </span>
            {c.status === 'proposed' ? (
              <span className="font-medium text-warning">to review</span>
            ) : (
              <span>{c.status}</span>
            )}
            {worst && (
              <span className={cn('inline-flex items-center gap-1', TONE_CLASSES[worst.tone].text)}>
                <span className={cn('size-1.5 rounded-full', TONE_CLASSES[worst.tone].bg)} />
                {worst.label}
              </span>
            )}
          </span>
        </span>
      </button>
    </li>
  );
}
