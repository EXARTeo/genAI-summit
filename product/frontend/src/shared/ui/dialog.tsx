import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';

interface BaseProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Element that opens it (rendered with asChild). */
  trigger?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  /** Buttons row at the bottom. */
  footer?: ReactNode;
  className?: string;
}

const overlay =
  'fixed inset-0 z-50 bg-background/60 backdrop-blur-sm data-[state=open]:animate-[overlay-in_200ms_ease-out]';

export interface DialogProps extends BaseProps {
  size?: 'sm' | 'md' | 'lg' | 'xl';
}

const SIZES = { sm: 'max-w-sm', md: 'max-w-lg', lg: 'max-w-2xl', xl: 'max-w-4xl' };

/** Centered modal. Controlled (`open` + `onOpenChange`) or with a `trigger`. */
export function Dialog({
  open,
  onOpenChange,
  trigger,
  title,
  description,
  children,
  footer,
  className,
  size = 'md',
}: DialogProps) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      {trigger && <DialogPrimitive.Trigger asChild>{trigger}</DialogPrimitive.Trigger>}
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={overlay} />
        <DialogPrimitive.Content
          className={cn(
            'fixed left-1/2 top-1/2 z-50 flex max-h-[85vh] w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-2xl border border-border bg-surface shadow-lift',
            'data-[state=open]:animate-[dialog-in_240ms_cubic-bezier(0.16,1,0.3,1)]',
            SIZES[size],
            className,
          )}
        >
          <Header title={title} description={description} />
          <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-5">{children}</div>
          {footer && (
            <div className="flex justify-end gap-2 border-t border-border px-6 py-4">{footer}</div>
          )}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

export interface SheetProps extends BaseProps {
  side?: 'right' | 'left';
  width?: string;
}

/** Side panel (drawer) for details and inspectors. */
export function Sheet({
  open,
  onOpenChange,
  trigger,
  title,
  description,
  children,
  footer,
  className,
  side = 'right',
  width = 'w-[min(36rem,100vw)]',
}: SheetProps) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      {trigger && <DialogPrimitive.Trigger asChild>{trigger}</DialogPrimitive.Trigger>}
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={overlay} />
        <DialogPrimitive.Content
          className={cn(
            'fixed inset-y-0 z-50 flex flex-col border-border bg-surface shadow-lift',
            side === 'right'
              ? 'right-0 border-l data-[state=open]:animate-[sheet-in-right_320ms_cubic-bezier(0.16,1,0.3,1)]'
              : 'left-0 border-r data-[state=open]:animate-[sheet-in-left_320ms_cubic-bezier(0.16,1,0.3,1)]',
            width,
            className,
          )}
        >
          <Header title={title} description={description} />
          <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">{children}</div>
          {footer && (
            <div className="flex justify-end gap-2 border-t border-border px-6 py-4">{footer}</div>
          )}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function Header({ title, description }: { title: ReactNode; description?: ReactNode }) {
  return (
    <div className="flex items-start gap-4 px-6 pb-4 pt-5">
      <div className="min-w-0 flex-1">
        <DialogPrimitive.Title className="text-lg font-semibold leading-tight">{title}</DialogPrimitive.Title>
        {description ? (
          <DialogPrimitive.Description className="mt-1 text-sm text-muted">{description}</DialogPrimitive.Description>
        ) : (
          <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
        )}
      </div>
      <DialogPrimitive.Close
        className="rounded-md p-1 text-muted transition-colors hover:bg-surface-muted hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label="Close"
      >
        <X className="size-4" />
      </DialogPrimitive.Close>
    </div>
  );
}

export const DialogClose = DialogPrimitive.Close;
