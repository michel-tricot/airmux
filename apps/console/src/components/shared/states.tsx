import { type ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/elements';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@/components/ui/empty';
import { queryErrorMessage } from '@/lib/errors';

export function LoadingState({ label = 'Loading...', className }: { label?: string; className?: string }) {
  return (
    <div role="status" className={cn('p-8 text-center text-muted-foreground font-mono text-sm', className)}>
      {label}
    </div>
  );
}

export function ErrorState({
  message,
  error,
  resource,
  onRetry,
  className,
}: {
  message?: string;
  error?: unknown;
  resource?: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div role="alert" className={cn('p-8 text-center space-y-3', className)}>
      <p className="text-sm text-destructive">{message ?? queryErrorMessage(error, resource)}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

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
    <Empty className={cn(Icon ? 'p-12' : 'p-8', 'gap-0 border-0 text-muted-foreground', className)}>
      <EmptyHeader>
        {Icon && (
          <EmptyMedia>
            <Icon className="h-12 w-12 opacity-20" />
          </EmptyMedia>
        )}
        <EmptyDescription>{children}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}
