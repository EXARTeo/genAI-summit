import { Menu, Search } from 'lucide-react';
import { useUiStore } from '@/shared/stores/ui';
import { IconButton } from '@/shared/ui';
import { ThemeToggle } from './ThemeToggle';

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);

export function TopBar() {
  const setCommandOpen = useUiStore((s) => s.setCommandOpen);
  const setMobileNavOpen = useUiStore((s) => s.setMobileNavOpen);
  return (
    <header className="sticky top-0 z-30 flex h-[var(--topbar-height)] items-center gap-3 border-b border-border bg-background/75 px-4 backdrop-blur-xl lg:px-6">
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
        className="group flex h-9 w-full max-w-md items-center gap-2 rounded-lg border border-border bg-surface/80 px-3 text-sm text-muted shadow-sm transition-all hover:border-primary/40 hover:text-text"
      >
        <Search className="size-4" />
        <span className="flex-1 text-left">Search or jump to…</span>
        <kbd className="hidden rounded border border-border bg-surface-muted px-1.5 font-sans text-[11px] sm:inline">
          {isMac ? '⌘' : 'Ctrl'} K
        </kbd>
      </button>
      <div className="ml-auto flex items-center gap-1">
        <ThemeToggle />
      </div>
    </header>
  );
}
