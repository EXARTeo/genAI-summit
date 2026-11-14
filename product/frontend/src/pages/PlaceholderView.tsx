import type { ReactNode } from 'react';
import { EmptyState, PageHeader, SkeletonCard } from '@/shared/ui';

/** Stub for a page whose feature is not built yet: header, skeleton preview, empty state. */
export function PlaceholderView({
  title,
  description,
  icon,
  emptyTitle,
  emptyDescription,
}: {
  title: string;
  description: string;
  icon: ReactNode;
  emptyTitle: string;
  emptyDescription: string;
}) {
  return (
    <div>
      <PageHeader title={title} description={description} icon={icon} />
      <div className="mb-6 grid gap-4 opacity-60 sm:grid-cols-2 xl:grid-cols-3" aria-hidden>
        <SkeletonCard />
        <SkeletonCard className="hidden sm:block" />
        <SkeletonCard className="hidden xl:block" />
      </div>
      <EmptyState icon={icon} title={emptyTitle} description={emptyDescription} />
    </div>
  );
}
