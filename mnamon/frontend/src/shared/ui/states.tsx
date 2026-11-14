import { AlertTriangle, Inbox, RefreshCw } from 'lucide-react';
import type { ReactNode } from 'react';
import { ApiError } from '@/shared/lib/api';
import { cn } from '@/shared/lib/utils';
import { Button } from './button';

export interface EmptyStateProps {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
  /** Smaller variant for inside cards. */
  compact?: boolean;
}

export function EmptyState({ icon, title, description, action, className, compact }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'fade-in flex flex-col items-center justify-center text-center',
        compact ? 'gap-2 px-4 py-8' : 'gap-2 rounded-xl border border-dashed border-border px-6 py-14',
        className,
      )}
    >
      <div
        className={cn(
          'mb-1 grid place-items-center rounded-lg border border-border bg-surface-muted text-muted',
          compact ? 'size-8 [&_svg]:size-4' : 'size-10 [&_svg]:size-5',
        )}
      >
        {icon ?? <Inbox />}
      </div>
      <h3 className="text-sm font-semibold">{title}</h3>
      {description && <p className="max-w-sm text-sm text-muted">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export interface ErrorStateProps {
  title?: ReactNode;
  error?: unknown;
  onRetry?: () => void;
  className?: string;
  compact?: boolean;
}

export function ErrorState({
  title = 'Something went wrong',
  error,
  onRetry,
  className,
  compact,
}: ErrorStateProps) {
  const message =
    error instanceof ApiError
      ? error.isNotFound
        ? 'Not found, or it belongs to someone else.'
        : error.message
      : error instanceof Error
        ? error.message
        : typeof error === 'string'
          ? error
          : undefined;
  const requestId = error instanceof ApiError ? error.requestId : null;
  return (
    <div
      role="alert"
      className={cn(
        'fade-in flex flex-col items-center justify-center gap-3 text-center',
        compact ? 'px-4 py-8' : 'rounded-xl border border-danger/25 bg-danger/5 px-6 py-12',
        className,
      )}
    >
      <div className="grid size-10 place-items-center rounded-lg bg-danger/10 text-danger">
        <AlertTriangle className="size-5" />
      </div>
      <h3 className="text-sm font-semibold">{title}</h3>
      {message && <p className="max-w-md text-sm text-muted">{message}</p>}
      {requestId && <code className="text-[11px] text-muted">request {requestId}</code>}
      {onRetry && (
        <Button variant="secondary" size="sm" leftIcon={<RefreshCw />} onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
