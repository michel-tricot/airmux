import { forwardRef, type HTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

type AlertVariant = 'default' | 'destructive' | 'success' | 'warning';

const alertVariants: Record<AlertVariant, string> = {
  default: 'border-border bg-background text-foreground',
  destructive: 'border-destructive/20 bg-destructive/10 text-destructive',
  success: 'border-success/20 bg-success/10 text-foreground [&>svg]:text-success',
  warning: 'border-warning/20 bg-warning/10 text-foreground [&>svg]:text-warning',
};

export const Alert = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement> & { variant?: AlertVariant }>(
  ({ className, variant = 'default', role = 'alert', ...props }, ref) => (
    <div
      ref={ref}
      role={role}
      className={cn(
        'relative flex w-full items-start gap-3 rounded-md border px-4 py-3 text-sm [&>svg]:mt-0.5 [&>svg]:h-5 [&>svg]:w-5 [&>svg]:shrink-0',
        alertVariants[variant],
        className,
      )}
      {...props}
    />
  ),
);
Alert.displayName = 'Alert';

export const AlertTitle = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn('mb-1 font-medium leading-none tracking-tight', className)} {...props} />
));
AlertTitle.displayName = 'AlertTitle';

export const AlertDescription = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn('text-sm [&_p]:leading-relaxed', className)} {...props} />
));
AlertDescription.displayName = 'AlertDescription';
