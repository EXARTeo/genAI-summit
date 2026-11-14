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
      'rounded-xl border border-border bg-surface text-text',
      interactive && 'hover-lift cursor-pointer hover:border-text/20',
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

export function CardHeader({
  title,
  description,
  icon,
  actions,
  className,
  children,
  ...props
}: CardHeaderProps) {
  return (
    <div className={cn('flex items-start gap-3 px-4 pb-2 pt-4', className)} {...props}>
      {icon && (
        <div className="grid size-7 shrink-0 place-items-center rounded-md border border-border bg-surface-muted text-muted [&_svg]:size-3.5">
          {icon}
        </div>
      )}
      <div className="min-w-0 flex-1">
        {title && <h3 className="truncate text-sm font-semibold leading-7">{title}</h3>}
        {description && <p className="text-xs text-muted">{description}</p>}
        {children}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
    </div>
  );
}

export function CardContent({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-4 pb-4 pt-2', className)} {...props} />;
}

export function CardFooter({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'flex items-center gap-2 border-t border-border px-4 py-2.5 text-xs text-muted',
        className,
      )}
      {...props}
    />
  );
}
