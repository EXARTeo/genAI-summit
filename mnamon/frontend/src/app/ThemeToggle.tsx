import { Monitor, Moon, Sun } from 'lucide-react';
import { forwardRef, type ComponentPropsWithoutRef } from 'react';
import { useTheme } from '@/shared/hooks/useTheme';
import { INTERACTIVE_SURFACE } from '@/shared/lib/consts/ui';
import { cn } from '@/shared/lib/utils';
import type { ThemePreference } from '@/shared/stores/theme';
import { DropdownMenu, IconButton, Tooltip } from '@/shared/ui';

const OPTIONS: { value: ThemePreference; label: string; icon: JSX.Element }[] = [
  { value: 'light', label: 'Light', icon: <Sun /> },
  { value: 'dark', label: 'Dark', icon: <Moon /> },
  { value: 'system', label: 'System', icon: <Monitor /> },
];

const LABELS: Record<ThemePreference, string> = { light: 'Light', dark: 'Dark', system: 'System' };

/** The sidebar row recipe (Sidebar.tsx ROW), so the theme row lines up with the nav. */
const ROW = `group/nav relative flex h-9 w-full items-center gap-1 rounded-xl px-1.5 text-sm text-text/90 outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring ${INTERACTIVE_SURFACE}`;

/** The sidebar footer's trigger: icon + "Theme" + the current choice; icon only when collapsed. */
const ThemeRowTrigger = forwardRef<
  HTMLButtonElement,
  ComponentPropsWithoutRef<'button'> & { collapsed: boolean; dark: boolean; preference: ThemePreference }
>(function ThemeRowTrigger({ collapsed, dark, preference, className, ...props }, ref) {
  const Icon = dark ? Moon : Sun;
  return (
    <button
      ref={ref}
      type="button"
      aria-label={`Theme: ${LABELS[preference]}`}
      data-testid="theme-toggle"
      className={cn(ROW, className)}
      {...props}
    >
      <span className="grid size-9 shrink-0 place-items-center">
        <Icon className="size-[18px] transition-transform duration-300 ease-out motion-safe:group-hover/nav:rotate-12" />
      </span>
      {!collapsed && (
        <>
          <span className="sidebar-reveal flex-1 text-left">Theme</span>
          <span className="sidebar-reveal mr-2 text-xs text-muted">{LABELS[preference]}</span>
        </>
      )}
    </button>
  );
});

/**
 * Light / dark / system. `variant="icon"` is a bare icon button; `variant="row"` is the
 * sidebar footer row (pinned to the rail's bottom), icon-only with a tooltip when collapsed.
 */
export function ThemeToggle({
  variant = 'icon',
  collapsed = false,
}: {
  variant?: 'icon' | 'row';
  collapsed?: boolean;
}) {
  const { preference, resolved, setPreference } = useTheme();
  const items = OPTIONS.map((o) => ({
    label: o.label,
    icon: o.icon,
    checked: preference === o.value,
    onSelect: () => setPreference(o.value),
  }));
  if (variant === 'row') {
    const trigger = (
      <ThemeRowTrigger collapsed={collapsed} dark={resolved === 'dark'} preference={preference} />
    );
    return (
      <DropdownMenu
        side={collapsed ? 'right' : 'top'}
        align="start"
        trigger={
          collapsed ? (
            <Tooltip content={`Theme: ${LABELS[preference]}`} side="right">
              {trigger}
            </Tooltip>
          ) : (
            trigger
          )
        }
        items={items}
      />
    );
  }
  return (
    <DropdownMenu
      trigger={
        <IconButton
          label={`Theme: ${preference}`}
          tooltip={false}
          icon={resolved === 'dark' ? <Moon /> : <Sun />}
          data-testid="theme-toggle"
        />
      }
      items={items}
    />
  );
}
