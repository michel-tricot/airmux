import { type ReactNode } from 'react';
import { CircleAlert, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Alert, AlertDescription, AlertTitle, Button } from '@/components/ui/elements';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@/components/ui/empty';
import { queryErrorMessage, queryErrorTitle } from '@/lib/errors';

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
  const description = message ?? queryErrorMessage(error, resource);

  return (
    <div className={cn('p-6', className)}>
      <Alert variant="destructive" className="mx-auto max-w-2xl text-foreground shadow-sm [&>svg]:text-destructive">
        <CircleAlert aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <AlertTitle className="font-mono text-xs font-bold uppercase tracking-wider">{queryErrorTitle(error, message)}</AlertTitle>
          <AlertDescription className="text-muted-foreground">{description}</AlertDescription>
          {onRetry && (
            <Button
              variant="outline"
              size="sm"
              onClick={onRetry}
              className="mt-3 gap-2 border-destructive/20 text-foreground hover:border-destructive/40 hover:bg-destructive/10"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
              Retry
            </Button>
          )}
        </div>
      </Alert>
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
