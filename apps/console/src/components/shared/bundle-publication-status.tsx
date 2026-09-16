import type { BundlePublicationStatusOut } from '@workspace/api-client-react';
import { Alert, AlertDescription, AlertTitle, Badge, Button, Card } from '@/components/ui/elements';
import { ErrorState } from '@/components/shared/states';

export function BundlePublicationStatus({
  publication,
  isLoading,
  isError,
  error,
  onRetry,
  onRepublish,
  republishPending,
}: {
  publication: BundlePublicationStatusOut | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  onRetry: () => void;
  onRepublish?: () => void;
  republishPending?: boolean;
}) {
  if (isLoading) return null;
  if (isError) return <ErrorState error={error} resource="configuration publication status" onRetry={onRetry} />;
  if (!publication) return null;

  if (publication.status === 'failed') {
    return (
      <Alert variant="destructive">
        <AlertTitle className="flex items-center justify-between gap-3">
          <span>Publication failed</span>
          {onRepublish && (
            <Button size="sm" variant="outline" disabled={republishPending} onClick={onRepublish}>
              {republishPending ? 'Queueing...' : 'Republish'}
            </Button>
          )}
        </AlertTitle>
        <AlertDescription>
          {publication.failure?.message ?? 'Configuration could not be published'}. The previous bundle remains available to data planes.
        </AlertDescription>
      </Alert>
    );
  }

  const current = publication.status === 'current';
  return (
    <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <Badge variant={current ? 'success' : 'warning'}>{current ? 'Current' : 'Publishing configuration'}</Badge>
          {publication.latest_bundle && <span className="font-mono text-xs text-muted-foreground">v{publication.latest_bundle.version}</span>}
        </div>
        <p className="text-sm text-muted-foreground">
          {current
            ? 'Published by the control plane. Data planes adopt it on their next successful poll.'
            : `Saved and queued as configuration revision ${publication.desired_revision}. The previous bundle remains active until publication succeeds.`}
        </p>
      </div>
    </Card>
  );
}
