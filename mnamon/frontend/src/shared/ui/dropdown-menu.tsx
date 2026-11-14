import * as Menu from '@radix-ui/react-dropdown-menu';
import { Check } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';

export type DropdownItem =
  | {
      type?: 'item';
      label: ReactNode;
      icon?: ReactNode;
      onSelect?: () => void;
      shortcut?: string;
      danger?: boolean;
      disabled?: boolean;
      checked?: boolean;
    }
  | { type: 'separator' }
  | { type: 'label'; label: ReactNode };

export interface DropdownMenuProps {
  trigger: ReactNode;
  items: DropdownItem[];
  align?: 'start' | 'center' | 'end';
  className?: string;
}

const itemCls =
  'relative flex cursor-default select-none items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none transition-colors data-[disabled]:pointer-events-none data-[highlighted]:bg-surface-muted data-[disabled]:opacity-50 [&_svg]:size-4 [&_svg]:text-muted';

/** Data-driven dropdown menu. */
export function DropdownMenu({ trigger, items, align = 'end', className }: DropdownMenuProps) {
  return (
    <Menu.Root>
      <Menu.Trigger asChild>{trigger}</Menu.Trigger>
      <Menu.Portal>
        <Menu.Content
          align={align}
          sideOffset={6}
          className={cn(
            'z-50 min-w-[11rem] rounded-xl border border-border bg-surface p-1 text-text shadow-lift',
            'data-[state=open]:animate-[fade-in_160ms_ease-out]',
            className,
          )}
        >
          {items.map((it, i) => {
            if (it.type === 'separator') return <Menu.Separator key={i} className="my-1 h-px bg-border" />;
            if (it.type === 'label')
              return (
                <Menu.Label key={i} className="px-2 py-1 text-xs font-medium text-muted">
                  {it.label}
                </Menu.Label>
              );
            return (
              <Menu.Item
                key={i}
                disabled={it.disabled}
                onSelect={it.onSelect}
                className={cn(itemCls, it.danger && 'text-danger [&_svg]:text-danger')}
              >
                {it.icon}
                <span className="flex-1">{it.label}</span>
                {it.checked && <Check className="!text-primary" />}
                {it.shortcut && <kbd className="text-[11px] text-muted">{it.shortcut}</kbd>}
              </Menu.Item>
            );
          })}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}
