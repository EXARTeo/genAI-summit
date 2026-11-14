import { motion, useReducedMotion } from 'framer-motion';
import { PanelLeft, Search } from 'lucide-react';
import { Link, NavLink } from 'react-router-dom';
import { env } from '@/shared/lib/env';
import { INTERACTIVE_SURFACE, RAISED_ON_FRAME } from '@/shared/lib/consts/ui';
import { cn } from '@/shared/lib/utils';
import { useNavBadges } from '@/shared/stores/nav';
import { useUiStore } from '@/shared/stores/ui';
import { LogoMark, PRODUCT_DESCRIPTOR, PRODUCT_NAME, Tooltip, Wordmark } from '@/shared/ui';
import { NAV_ITEMS, type NavItem } from './nav';
import { SidebarSlotTarget } from './sidebarSlot';

/*
 * The rail follows magenticx's ChatSidebar (agentic_ui/src/features/chat/components/ChatSidebar.tsx):
 * - every row has the same px-1.5 lead and a size-9 icon box in both states, so the
 *   icons stay pinned in place while only the rail width animates around them;
 * - labels are display:none while collapsed and fade in (sidebar-reveal) on expand;
 * - the open page wears a soft pill in the theme colour (bg 10% + inset 1px ring at
 *   16%) that glides between entries on a short ease-out tween, position only;
 * - the top action is a raised card (border + shadow-sm on the card colour) that
 *   flattens to a plain icon row when the rail collapses.
 */
const ROW = `group/nav relative flex h-9 w-full items-center gap-1 rounded-xl px-1.5 text-sm text-text/90 outline-none transition-colors duration-150 ${INTERACTIVE_SURFACE}`;
const ICON_BOX = 'relative z-[1] grid size-9 shrink-0 place-items-center';
const ICON = 'size-[18px] transition-transform duration-300 ease-out motion-safe:group-hover/nav:scale-110';
const PILL_TWEEN = { type: 'tween', duration: 0.22, ease: [0.16, 1, 0.3, 1] } as const;

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);

function Label({
  collapsed,
  className,
  children,
}: {
  collapsed: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  if (collapsed) return null;
  return <span className={cn('sidebar-reveal relative z-[1] whitespace-nowrap', className)}>{children}</span>;
}

function NavEntry({
  item,
  collapsed,
  layoutGroup,
  onNavigate,
}: {
  item: NavItem;
  collapsed: boolean;
  layoutGroup: string;
  onNavigate?: () => void;
}) {
  const count = useNavBadges((s) => s.badges[item.id] ?? 0);
  const reduceMotion = useReducedMotion();
  const Icon = item.icon;
  return (
    <Tooltip content={item.label} side="right" disabled={!collapsed}>
      <NavLink
        to={item.to}
        end={item.to === '/'}
        onClick={onNavigate}
        // A string, not a function: the collapsed rail's Tooltip (Radix Slot) would stringify a
        // className function. NavLink adds .active itself.
        className={cn(ROW, '[&.active]:font-medium [&.active]:text-text [&.active]:hover:bg-transparent')}
      >
        {({ isActive }) => (
          <>
            {isActive && (
              <motion.span
                layoutId={`${layoutGroup}-active`}
                layout="position"
                aria-hidden
                data-indicator="page"
                className="absolute inset-0 z-0 rounded-xl bg-primary/10 ring-1 ring-inset ring-primary/[0.16]"
                transition={reduceMotion ? { duration: 0 } : PILL_TWEEN}
              />
            )}
            <span className={ICON_BOX}>
              <Icon className={cn(ICON, isActive && 'text-primary')} />
              {count > 0 && collapsed && (
                <span
                  className="num absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-warning px-1 text-[10px] font-semibold leading-none text-warning-foreground"
                  aria-label={`${count} pending`}
                >
                  {count > 99 ? '99+' : count}
                </span>
              )}
            </span>
            <Label collapsed={collapsed} className="flex-1 truncate">
              {item.label}
            </Label>
            {count > 0 && !collapsed && (
              <span
                className="num sidebar-reveal relative z-[1] mr-1.5 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-warning/15 px-1.5 text-2xs font-semibold text-warning"
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

export function SidebarContent({
  collapsed,
  layoutGroup = 'nav',
  onNavigate,
}: {
  collapsed: boolean;
  /** Distinct per rendered copy (rail vs drawer) so their pills never glide across. */
  layoutGroup?: string;
  onNavigate?: () => void;
}) {
  const toggle = useUiStore((s) => s.toggleSidebar);
  const setCommandOpen = useUiStore((s) => s.setCommandOpen);
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-col gap-2.5 px-2 pb-2 pt-4">
        {/* Brand row: when collapsed, hovering the mark turns it into the expand
            control (magenticx); when open, the collapse control sits at the right. */}
        <div className="relative">
          <Tooltip content="Expand sidebar" side="right" disabled={!collapsed}>
            <Link
              to="/"
              onClick={(e) => {
                if (collapsed) {
                  e.preventDefault();
                  toggle();
                }
                onNavigate?.();
              }}
              aria-label={collapsed ? 'Expand sidebar' : `${PRODUCT_NAME} home`}
              className={cn(ROW, 'group/brand h-12 gap-2')}
            >
              <span className="relative grid size-9 shrink-0 place-items-center">
                <LogoMark
                  className={cn('size-8 transition-opacity', collapsed && 'group-hover/brand:opacity-0')}
                />
                {collapsed && (
                  <PanelLeft className="absolute size-5 text-text opacity-0 transition-opacity group-hover/brand:opacity-100" />
                )}
              </span>
              <Label collapsed={collapsed} className="flex min-w-0 flex-col leading-tight">
                <Wordmark className="truncate text-base" />
                <span className="mt-1 truncate text-xs font-normal text-muted">{PRODUCT_DESCRIPTOR}</span>
              </Label>
            </Link>
          </Tooltip>
          {!collapsed && (
            <button
              type="button"
              onClick={toggle}
              aria-label="Collapse sidebar"
              className="sidebar-reveal absolute right-1 top-1.5 hidden size-9 place-items-center rounded-xl text-muted transition-colors hover:bg-hover hover:text-text lg:grid"
            >
              <PanelLeft className="size-5" />
            </button>
          )}
        </div>

        {/* The raised card: magenticx's "New chat" treatment, here for search / ⌘K.
            Its 1px border + px-[5px] give the same 6px lead as the rows, so the icon
            never moves; collapsed, it flattens to a plain icon row. */}
        <Tooltip content={`Search (${isMac ? '⌘' : 'Ctrl'} K)`} side="right" disabled={!collapsed}>
          <button
            type="button"
            onClick={() => {
              onNavigate?.();
              setCommandOpen(true);
            }}
            aria-label="Search or jump to"
            className={cn(
              ROW,
              'h-10 border font-medium text-text',
              collapsed ? 'border-transparent px-[5px]' : cn('px-[5px]', RAISED_ON_FRAME),
            )}
          >
            <span className={ICON_BOX}>
              <Search className={cn(ICON, 'motion-safe:group-hover/nav:-rotate-12')} />
            </span>
            <Label collapsed={collapsed} className="flex-1 text-left">
              Search
            </Label>
            {!collapsed && (
              <kbd className="sidebar-reveal mr-1.5 rounded-md border border-border bg-surface-muted px-1.5 font-sans text-2xs text-muted">
                {isMac ? '⌘' : 'Ctrl'} K
              </kbd>
            )}
          </button>
        </Tooltip>

        {/* Rows stacked with no gap (36px apart), as magenticx's are. */}
        <nav aria-label="Main" className="flex flex-col">
          {NAV_ITEMS.map((item) => (
            <NavEntry
              key={item.id}
              item={item}
              collapsed={collapsed}
              layoutGroup={layoutGroup}
              onNavigate={onNavigate}
            />
          ))}
        </nav>
      </div>

      {/* Feature-owned region (e.g. the chat's conversation list): see sidebarSlot.tsx. */}
      <SidebarSlotTarget className={cn('min-h-0 flex-1 overflow-y-auto px-2', collapsed && 'hidden')} />

      {!collapsed && env.useMocks && (
        <div className="sidebar-reveal flex items-center gap-2 px-4 py-3 text-2xs text-muted">
          <span className="size-1.5 rounded-full bg-warning" />
          Demo data (mock mode)
        </div>
      )}
    </div>
  );
}

/** Desktop rail (collapsible). It sits on the app frame; the mobile drawer is in WorkspaceShell. */
export function Sidebar() {
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  return (
    <aside
      data-state={collapsed ? 'collapsed' : 'expanded'}
      className={cn(
        'sticky top-0 hidden h-svh shrink-0 overflow-hidden transition-[width] duration-200 ease-linear lg:block',
        collapsed ? 'w-sidebar-collapsed' : 'w-sidebar',
      )}
    >
      <SidebarContent collapsed={collapsed} layoutGroup="rail" />
    </aside>
  );
}
