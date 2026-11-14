import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { Loader2 } from 'lucide-react';
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';
import { Tooltip } from './tooltip';

export const buttonVariants = cva(
  'inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-lg text-sm font-medium transition-[background-color,color,box-shadow,border-color] duration-150 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-1 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary: 'bg-primary text-primary-foreground shadow-card hover:bg-primary/90',
        secondary: 'border border-border bg-surface text-text shadow-card hover:bg-surface-muted',
        ghost: 'text-muted hover:bg-surface-muted hover:text-text',
        outline: 'border border-border bg-transparent text-text hover:bg-surface-muted',
        accent: 'bg-accent text-accent-foreground shadow-card hover:bg-accent/90',
        danger: 'bg-danger text-danger-foreground shadow-card hover:bg-danger/90',
        warning: 'bg-warning text-warning-foreground shadow-card hover:bg-warning/90',
        link: 'h-auto px-0 text-primary underline-offset-4 hover:underline',
      },
      size: {
        sm: 'h-7 px-2.5 text-xs [&_svg]:size-3.5',
        md: 'h-8 px-3',
        lg: 'h-10 px-4 text-base',
        icon: 'size-8',
        'icon-sm': 'size-7 [&_svg]:size-3.5',
      },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant, size, asChild, loading, leftIcon, rightIcon, children, disabled, ...props },
    ref,
  ) => {
    if (asChild) {
      return (
        <Slot ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props}>
          {children}
        </Slot>
      );
    }
    return (
      <button
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {loading ? <Loader2 className="animate-spin" aria-hidden /> : leftIcon}
        {children}
        {rightIcon}
      </button>
    );
  },
);
Button.displayName = 'Button';

export interface IconButtonProps extends Omit<ButtonProps, 'leftIcon' | 'rightIcon' | 'children'> {
  /** Accessible name; also shown as a tooltip. */
  label: string;
  icon: ReactNode;
  tooltip?: boolean;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ label, icon, tooltip = true, variant = 'ghost', size = 'icon', ...props }, ref) => {
    const btn = (
      <Button ref={ref} variant={variant} size={size} aria-label={label} {...props}>
        {icon}
      </Button>
    );
    return tooltip ? <Tooltip content={label}>{btn}</Tooltip> : btn;
  },
);
IconButton.displayName = 'IconButton';
