import { type ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/elements';

/** Consistent placeholder while a data-driven view loads. */
export function LoadingState({ label = 'Loading...', className }: { label?: string; className?: string }) {
  return <div className={cn('p-8 text-center text-muted-foreground font-mono text-sm', className)}>{label}</div>;
}

/** Consistent query-error placeholder with a retry affordance. */
export function ErrorState({
  message = 'Something went wrong loading this data.',
  onRetry,
  className,
}: {
  message?: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div className={cn('p-8 text-center space-y-3', className)}>
      <p className="text-sm text-destructive">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

/** Consistent empty placeholder for lists and tables. */
export function EmptyState({
  icon: Icon,
  children,
  className,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn(Icon ? 'p-12' : 'p-8', 'text-center text-muted-foreground', className)}>
      {Icon && <Icon className="w-12 h-12 mx-auto mb-4 opacity-20" />}
      {typeof children === 'string' ? <p>{children}</p> : children}
    </div>
  );
}
