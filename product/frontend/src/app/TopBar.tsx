import { Menu, Search } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { useUiStore } from '@/shared/stores/ui';
import { IconButton } from '@/shared/ui';
import { NAV_ITEMS } from './nav';
import { ThemeToggle } from './ThemeToggle';

function useSectionLabel(): string {
  const { pathname } = useLocation();
  const item =
    NAV_ITEMS.find((i) => i.to !== '/' && (pathname === i.to || pathname.startsWith(`${i.to}/`))) ??
    (pathname === '/' ? NAV_ITEMS.find((i) => i.to === '/') : undefined);
  return item?.label ?? '';
}

/** The main card's header: it scrolls with nothing, sticks to the card's top edge. */
export function TopBar() {
  const setCommandOpen = useUiStore((s) => s.setCommandOpen);
  const setMobileNavOpen = useUiStore((s) => s.setMobileNavOpen);
  const section = useSectionLabel();
  return (
    <header className="sticky top-0 z-30 flex h-[var(--topbar-height)] shrink-0 items-center gap-2 bg-[color-mix(in_srgb,var(--shell-card)_85%,transparent)] px-3 backdrop-blur-md lg:px-6">
      <IconButton
        label="Open menu"
        icon={<Menu />}
        tooltip={false}
        className="lg:hidden"
        onClick={() => setMobileNavOpen(true)}
      />
      <span className="truncate text-sm font-medium text-muted">{section}</span>
      <div className="ml-auto flex items-center gap-1">
        <IconButton
          label="Search or jump to"
          icon={<Search />}
          tooltip={false}
          className="lg:hidden"
          onClick={() => setCommandOpen(true)}
        />
        <ThemeToggle />
      </div>
    </header>
  );
}
