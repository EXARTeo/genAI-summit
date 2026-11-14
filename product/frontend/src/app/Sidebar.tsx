import { AnimatePresence, motion } from 'framer-motion';
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import { env } from '@/shared/lib/env';
import { cn } from '@/shared/lib/utils';
import { useNavBadges } from '@/shared/stores/nav';
import { useUiStore } from '@/shared/stores/ui';
import { Logo, Tooltip } from '@/shared/ui';
import { NAV_ITEMS, SETTINGS_ITEM, type NavItem } from './nav';

function NavEntry({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavItem;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const count = useNavBadges((s) => s.badges[item.id] ?? 0);
  const Icon = item.icon;
  return (
    <Tooltip content={item.label} side="right" disabled={!collapsed}>
      <NavLink
        to={item.to}
        end={item.to === '/'}
        onClick={onNavigate}
        className={({ isActive }) =>
          cn(
            'group relative flex h-8 items-center gap-2.5 rounded-md px-2 text-sm font-medium transition-colors duration-150',
            isActive ? 'text-text' : 'text-muted hover:bg-surface-muted/70 hover:text-text',
            collapsed && 'justify-center px-0',
          )
        }
      >
        {({ isActive }) => (
          <>
            {isActive && (
              <motion.span
                layoutId="nav-active"
                className="absolute inset-0 rounded-md bg-surface-muted"
                transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
              />
            )}
            <Icon className={cn('relative size-4 shrink-0', isActive && 'text-primary')} />
            {!collapsed && <span className="relative flex-1 truncate">{item.label}</span>}
            {count > 0 && (
              <span
                className={cn(
                  'num relative grid h-[18px] min-w-[18px] place-items-center rounded-full bg-warning/15 px-1.5 text-2xs font-semibold text-warning',
                  collapsed &&
                    'absolute right-1 top-0.5 h-3.5 min-w-3.5 bg-warning px-1 text-[9px] text-warning-foreground',
                )}
                aria-label={`${count} pending`}
              >
                {count > 99 ? '99+' : count}
              </span>
            )}
          </>
        )}
      </NavLink>
    </Tooltip>
  );
}

export function SidebarContent({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const toggle = useUiStore((s) => s.toggleSidebar);
  return (
    <div className="flex h-full flex-col">
      <div
        className={cn('flex h-[var(--topbar-height)] items-center px-4', collapsed && 'justify-center px-0')}
      >
        <Logo collapsed={collapsed} />
      </div>
      <nav aria-label="Main" className="flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
        {NAV_ITEMS.map((item) => (
          <NavEntry key={item.id} item={item} collapsed={collapsed} onNavigate={onNavigate} />
        ))}
      </nav>
      <div className="space-y-0.5 px-2 py-2">
        <NavEntry item={SETTINGS_ITEM} collapsed={collapsed} onNavigate={onNavigate} />
        <AnimatePresence initial={false}>
          {!collapsed && env.useMocks && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex items-center gap-2 px-2 py-1.5 text-2xs text-muted"
            >
              <span className="size-1.5 rounded-full bg-warning" />
              Demo data (mock mode)
            </motion.div>
          )}
        </AnimatePresence>
        <button
          type="button"
          onClick={toggle}
          className={cn(
            'hidden h-8 w-full items-center gap-2.5 rounded-md px-2 text-sm text-muted transition-colors hover:bg-surface-muted/70 hover:text-text lg:flex',
            collapsed && 'justify-center px-0',
          )}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
          {!collapsed && <span>Collapse</span>}
        </button>
      </div>
    </div>
  );
}

/** Desktop sidebar (collapsible). The mobile drawer is in WorkspaceShell. */
export function Sidebar() {
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  return (
    <motion.aside
      initial={false}
      animate={{ width: collapsed ? 'var(--sidebar-width-collapsed)' : 'var(--sidebar-width)' }}
      transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      className="sticky top-0 hidden h-screen shrink-0 border-r border-border bg-background lg:block"
    >
      <SidebarContent collapsed={collapsed} />
    </motion.aside>
  );
}
