import * as DialogPrimitive from '@radix-ui/react-dialog';
import { Command } from 'cmdk';
import { Boxes, Monitor, Moon, Search, Sun } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useSystems } from '@/features/systems/hooks/useSystems';
import { systemRoutes } from '@/features/systems/lib/routes';
import { useHotkey } from '@/shared/hooks/useHotkey';
import { useThemeStore } from '@/shared/stores/theme';
import { useUiStore } from '@/shared/stores/ui';
import { NAV_ITEMS, SETTINGS_ITEM } from './nav';

const itemCls =
  'flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm text-text aria-selected:bg-primary/10 aria-selected:text-primary [&_svg]:size-4 [&_svg]:text-muted aria-selected:[&_svg]:text-primary';
const groupCls =
  '[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted';

/** ⌘K / Ctrl+K: jump to pages and systems, switch theme. */
export function CommandPalette() {
  const open = useUiStore((s) => s.commandOpen);
  const setOpen = useUiStore((s) => s.setCommandOpen);
  const setTheme = useThemeStore((s) => s.setPreference);
  const navigate = useNavigate();
  const systems = useSystems({ enabled: open });

  useHotkey('mod+k', () => setOpen(!useUiStore.getState().commandOpen));

  const run = (fn: () => void) => {
    setOpen(false);
    fn();
  };

  return (
    <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-background/60 backdrop-blur-sm data-[state=open]:animate-[overlay-in_160ms_ease-out]" />
        <DialogPrimitive.Content className="fixed left-1/2 top-[14vh] z-50 w-[calc(100%-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-2xl border border-border bg-surface shadow-lift data-[state=open]:animate-[dialog-in_200ms_cubic-bezier(0.16,1,0.3,1)]">
          <DialogPrimitive.Title className="sr-only">Command palette</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">
            Search pages, systems and actions
          </DialogPrimitive.Description>
          <Command loop className="flex flex-col">
            <div className="flex items-center gap-2 border-b border-border px-4">
              <Search className="size-4 text-muted" />
              <Command.Input
                autoFocus
                placeholder="Search pages, systems, actions…"
                className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
              />
              <kbd className="rounded border border-border px-1.5 text-[10px] text-muted">ESC</kbd>
            </div>
            <Command.List className="max-h-[50vh] overflow-y-auto p-2">
              <Command.Empty className="px-3 py-8 text-center text-sm text-muted">No results.</Command.Empty>
              <Command.Group heading="Go to" className={groupCls}>
                {[...NAV_ITEMS, SETTINGS_ITEM].map((item) => (
                  <Command.Item
                    key={item.id}
                    value={`${item.label} ${item.description}`}
                    onSelect={() => run(() => navigate(item.to))}
                    className={itemCls}
                  >
                    <item.icon />
                    <span className="flex-1">{item.label}</span>
                    <span className="truncate text-xs text-muted">{item.description}</span>
                  </Command.Item>
                ))}
              </Command.Group>
              {(systems.data?.length ?? 0) > 0 && (
                <Command.Group heading="Systems" className={groupCls}>
                  {systems.data!.map((s) => (
                    <Command.Item
                      key={s.id}
                      value={`${s.id} ${s.name}`}
                      onSelect={() => run(() => navigate(systemRoutes.detail(s.id)))}
                      className={itemCls}
                    >
                      <Boxes />
                      <span className="font-mono text-xs text-accent">{s.id}</span>
                      <span className="flex-1">{s.name}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              <Command.Group heading="Theme" className={groupCls}>
                <Command.Item
                  value="theme light"
                  onSelect={() => run(() => setTheme('light'))}
                  className={itemCls}
                >
                  <Sun /> Light theme
                </Command.Item>
                <Command.Item
                  value="theme dark"
                  onSelect={() => run(() => setTheme('dark'))}
                  className={itemCls}
                >
                  <Moon /> Dark theme
                </Command.Item>
                <Command.Item
                  value="theme system"
                  onSelect={() => run(() => setTheme('system'))}
                  className={itemCls}
                >
                  <Monitor /> System theme
                </Command.Item>
              </Command.Group>
            </Command.List>
          </Command>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
