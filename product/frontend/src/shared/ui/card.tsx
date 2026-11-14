import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Lift on hover (for clickable cards). */
  interactive?: boolean;
}

export const Card = forwardRef<HTMLDivElement, CardProps>(({ className, interactive, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      'rounded-xl border border-border bg-surface text-text shadow-card',
      interactive && 'hover-lift cursor-pointer hover:border-primary/40',
      className,
    )}
    {...props}
  />
));
Card.displayName = 'Card';

export interface CardHeaderProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  title?: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
}

export function CardHeader({ title, description, icon, actions, className, children, ...props }: CardHeaderProps) {
  return (
    <div className={cn('flex items-start gap-3 p-5 pb-3', className)} {...props}>
      {icon && (
        <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary [&_svg]:size-[18px]">
          {icon}
        </div>
      )}
      <div className="min-w-0 flex-1">
        {title && <h3 className="truncate text-[15px] font-semibold leading-tight">{title}</h3>}
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
        {children}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
    </div>
  );
}

export function CardContent({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-5 pt-2', className)} {...props} />;
}

export function CardFooter({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('flex items-center gap-2 border-t border-border px-5 py-3 text-sm text-muted', className)}
      {...props}
    />
  );
}
