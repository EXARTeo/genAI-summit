import { Menu, Search } from 'lucide-react';
import { useUiStore } from '@/shared/stores/ui';
import { IconButton } from '@/shared/ui';
import { ThemeToggle } from './ThemeToggle';

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);

export function TopBar() {
  const setCommandOpen = useUiStore((s) => s.setCommandOpen);
  const setMobileNavOpen = useUiStore((s) => s.setMobileNavOpen);
  return (
    <header className="sticky top-0 z-30 flex h-[var(--topbar-height)] items-center gap-2 border-b border-border bg-background/90 px-4 backdrop-blur-md lg:px-6">
      <IconButton
        label="Open menu"
        icon={<Menu />}
        tooltip={false}
        className="lg:hidden"
        onClick={() => setMobileNavOpen(true)}
      />
      <button
        type="button"
        onClick={() => setCommandOpen(true)}
        className="group flex h-8 w-full max-w-xs items-center gap-2 rounded-lg border border-border bg-surface px-2.5 text-sm text-muted transition-colors hover:border-text/20 hover:text-text"
      >
        <Search className="size-3.5" />
        <span className="flex-1 text-left">Search or jump to…</span>
        <kbd className="hidden rounded border border-border bg-surface-muted px-1 font-sans text-2xs sm:inline">
          {isMac ? '⌘' : 'Ctrl'} K
        </kbd>
      </button>
      <div className="ml-auto flex items-center gap-1">
        <ThemeToggle />
      </div>
    </header>
  );
}
