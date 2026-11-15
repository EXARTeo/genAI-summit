import { Slot } from '@radix-ui/react-slot';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef, type ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';

/** Wrap the app once (main.tsx). */
export const TooltipProvider = TooltipPrimitive.Provider;

export interface TooltipProps
  extends Omit<
    ComponentPropsWithoutRef<typeof TooltipPrimitive.Trigger>,
    'content' | 'children' | 'asChild'
  > {
  content: ReactNode;
  children: ReactNode;
  side?: 'top' | 'right' | 'bottom' | 'left';
  align?: 'start' | 'center' | 'end';
  delayDuration?: number;
  className?: string;
  /** Render nothing extra when false (e.g. an expanded sidebar label). */
  disabled?: boolean;
}

/**
 * Forwards its ref and extra props to the trigger, so it composes inside another `asChild`
 * trigger (e.g. as a DropdownMenu trigger: the menu's open handlers reach the button).
 */
export const Tooltip = forwardRef<ElementRef<typeof TooltipPrimitive.Trigger>, TooltipProps>(function Tooltip(
  { content, children, side = 'top', align = 'center', delayDuration = 250, className, disabled, ...props },
  ref,
) {
  if (disabled || !content) {
    return (
      <Slot ref={ref} {...props}>
        {children}
      </Slot>
    );
  }
  return (
    <TooltipPrimitive.Root delayDuration={delayDuration}>
      <TooltipPrimitive.Trigger asChild ref={ref} {...props}>
        {children}
      </TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          align={align}
          sideOffset={6}
          className={cn(
            'z-50 max-w-xs rounded-md border border-border bg-text px-2.5 py-1.5 text-xs font-medium text-background shadow-lift',
            'data-[state=delayed-open]:animate-[fade-in_150ms_ease-out]',
            className,
          )}
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
});
