import type { HTMLAttributes } from 'react';
import { cn } from '@/shared/lib/utils';

/** Shimmering placeholder block. Size it with classes (h-4 w-32, ...). */
export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden className={cn('skeleton h-4 w-full', className)} {...props} />;
}

/** A few lines of text-shaped skeletons. */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn('space-y-2', className)} aria-busy>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn('h-3.5', i === lines - 1 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  );
}

/** A card-shaped skeleton for grids. */
export function SkeletonCard({ className }: { className?: string }) {
  return (
    <div className={cn('rounded-xl border border-border bg-surface p-5 shadow-card', className)} aria-busy>
      <div className="flex items-center gap-3">
        <Skeleton className="size-9 rounded-lg" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      </div>
      <SkeletonText className="mt-5" lines={2} />
      <div className="mt-5 flex gap-2">
        <Skeleton className="h-5 w-16 rounded-full" />
        <Skeleton className="h-5 w-20 rounded-full" />
      </div>
    </div>
  );
}
