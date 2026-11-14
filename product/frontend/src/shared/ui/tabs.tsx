import * as TabsPrimitive from '@radix-ui/react-tabs';
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from 'react';
import { cn } from '@/shared/lib/utils';

const TabsRoot = TabsPrimitive.Root;

export const TabsList = forwardRef<
  ElementRef<typeof TabsPrimitive.List>,
  ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      'inline-flex h-8 max-w-full items-center gap-0.5 overflow-x-auto rounded-lg bg-surface-muted p-0.5 text-muted',
      className,
    )}
    {...props}
  />
));
TabsList.displayName = 'TabsList';

export const TabsTrigger = forwardRef<
  ElementRef<typeof TabsPrimitive.Trigger>,
  ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      'inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 text-sm font-medium transition-colors duration-150',
      'hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
      'data-[state=active]:bg-surface data-[state=active]:text-text data-[state=active]:shadow-card [&_svg]:size-3.5',
      className,
    )}
    {...props}
  />
));
TabsTrigger.displayName = 'TabsTrigger';

export const TabsContent = forwardRef<
  ElementRef<typeof TabsPrimitive.Content>,
  ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn('fade-in mt-4 focus-visible:outline-none', className)}
    {...props}
  />
));
TabsContent.displayName = 'TabsContent';

/** `<Tabs>` plus `Tabs.List`, `Tabs.Trigger`, `Tabs.Content`. */
export const Tabs = Object.assign(TabsRoot, {
  List: TabsList,
  Trigger: TabsTrigger,
  Content: TabsContent,
});
