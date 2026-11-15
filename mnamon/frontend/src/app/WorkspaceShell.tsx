import * as DialogPrimitive from '@radix-ui/react-dialog';
import { AnimatePresence, motion } from 'framer-motion';
import { Suspense } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { cn } from '@/shared/lib/utils';
import { ErrorBoundary } from '@/error_boundary';
import { pageTransition } from '@/shared/lib/motion';
import { useUiStore } from '@/shared/stores/ui';
import { Skeleton, SkeletonCard, Toaster } from '@/shared/ui';
import { CommandPalette } from './CommandPalette';
import { NavBadgesSync } from './NavBadgesSync';
import { Sidebar, SidebarContent } from './Sidebar';
import { TopBar } from './TopBar';

function PageFallback() {
  return (
    <div className="space-y-6" aria-busy>
      <div className="space-y-2">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-7 w-64" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 3 }, (_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    </div>
  );
}

/**
 * App frame (magenticx WorkspaceShell): the sidebar rail sits on a tinted frame and
 * the main content floats beside it as a rounded card (full-bleed below lg). The card
 * is the scroll container: the top bar sticks to its top edge and pages scroll inside.
 */
export function WorkspaceShell() {
  const location = useLocation();
  const mobileNavOpen = useUiStore((s) => s.mobileNavOpen);
  const setMobileNavOpen = useUiStore((s) => s.setMobileNavOpen);
  // A canvas page (the audit run graph) asks for the whole content area: no padding, no
  // max width, and it does its own panning instead of the card scrolling.
  const fullBleed = useUiStore((s) => s.fullBleed);
  // Animate between top-level sections only (/chat, /audits, /systems…). Keyed by the first
  // segment alone: with the id in the key, opening another chat or audit remounted the whole
  // page (the chat list rebuilt and every message faded in again on each click).
  const sectionKey = `/${location.pathname.split('/')[1] ?? ''}`;

  return (
    <div className="flex h-svh overflow-hidden bg-shell-frame">
      <Sidebar />

      <DialogPrimitive.Root open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-scrim lg:hidden" />
          <DialogPrimitive.Content className="fixed inset-y-0 left-0 z-50 w-sidebar bg-shell-frame shadow-pop data-[state=open]:animate-[sheet-in-left_260ms_cubic-bezier(0.16,1,0.3,1)] lg:hidden">
            <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
            <DialogPrimitive.Description className="sr-only">Main navigation</DialogPrimitive.Description>
            <SidebarContent
              collapsed={false}
              layoutGroup="drawer"
              onNavigate={() => setMobileNavOpen(false)}
            />
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>

      <div
        data-testid="main-card"
        className={cn(
          'relative flex min-w-0 flex-1 flex-col bg-shell-card lg:my-3 lg:mr-3 lg:rounded-shell lg:border lg:border-border/60 lg:shadow-shell',
          fullBleed ? 'overflow-hidden' : 'overflow-y-auto',
        )}
      >
        <TopBar />
        <main
          className={cn(
            'w-full flex-1',
            fullBleed ? 'flex min-h-0 flex-col' : 'mx-auto max-w-content px-4 py-6 lg:px-8 lg:py-8',
          )}
        >
          <ErrorBoundary resetKey={location.pathname}>
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={sectionKey}
                variants={pageTransition}
                initial="initial"
                animate="animate"
                exit="exit"
                className={cn(fullBleed && 'flex min-h-0 flex-1 flex-col')}
              >
                <Suspense fallback={<PageFallback />}>
                  <Outlet />
                </Suspense>
              </motion.div>
            </AnimatePresence>
          </ErrorBoundary>
        </main>
      </div>

      <NavBadgesSync />
      <CommandPalette />
      <Toaster />
    </div>
  );
}
