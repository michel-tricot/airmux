import { useState } from 'react';
import { Plus } from 'lucide-react';
import { AddProviderCredentialDialog } from '@/components/shared/provider-credential-dialog';
import { ProviderCredentialsTable } from '@/components/shared/provider-credentials-table';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { ErrorState } from '@/components/shared/states';
import { Badge, Button, Card } from '@/components/ui/elements';
import { useAddInstanceCredentialMutation, useInstanceProviderCredentials, useInstanceProviders } from '@/features/credentials/hooks';
import { providerCredentialAccess } from '@/features/credentials/policy';
import { catalogAccess } from '@/features/catalog/policy';
import { useAuthorization } from '@/features/permissions/hooks';
import { useInstancePublicationStatus } from '@/features/telemetry/hooks';

export default function ProviderKeys() {
  const authorization = useAuthorization('instance');
  const canRead = authorization.can(providerCredentialAccess.instance.read);
  const canReadCatalog = authorization.can(catalogAccess.instance.read);
  const canCreate = authorization.can(providerCredentialAccess.instance.create);
  const credentialsQuery = useInstanceProviderCredentials({ enabled: canRead });
  const taxonomyQuery = useInstanceProviders({ enabled: canReadCatalog });
  const publicationQuery = useInstancePublicationStatus({ enabled: canReadCatalog });
  const providers = taxonomyQuery.data?.providers ?? [];
  const addCredential = useAddInstanceCredentialMutation();
  const [addOpen, setAddOpen] = useState(false);

  return (
    <PageShell>
      <PageHeader
        title="Provider Keys"
        description="Manage default provider API keys available to every organization on this instance. Keys are tried in priority order."
        actions={
          canCreate &&
          canReadCatalog && (
            <Button onClick={() => setAddOpen(true)} disabled={taxonomyQuery.isLoading || taxonomyQuery.isError || providers.length === 0}>
              <Plus className="h-4 w-4" /> Add Key
            </Button>
          )
        }
      />

      {canReadCatalog && taxonomyQuery.isError && (
        <ErrorState error={taxonomyQuery.error} resource="provider catalog" onRetry={() => taxonomyQuery.refetch()} />
      )}
      {canReadCatalog && publicationQuery.isError && (
        <ErrorState error={publicationQuery.error} resource="instance publication status" onRetry={() => publicationQuery.refetch()} />
      )}
      {publicationQuery.data && (
        <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Badge
                variant={
                  publicationQuery.data.failed_organization_count > 0
                    ? 'destructive'
                    : publicationQuery.data.pending_organization_count > 0
                      ? 'warning'
                      : 'success'
                }
              >
                {publicationQuery.data.failed_organization_count > 0
                  ? 'Publication failed'
                  : publicationQuery.data.pending_organization_count > 0
                    ? 'Publishing configuration'
                    : 'Current'}
              </Badge>
              <span className="font-mono text-xs text-muted-foreground">revision {publicationQuery.data.global_desired_revision}</span>
            </div>
            <p className="text-sm text-muted-foreground">
              {publicationQuery.data.pending_organization_count} pending and {publicationQuery.data.failed_organization_count} failed organizations
            </p>
          </div>
        </Card>
      )}

      <ProviderCredentialsTable
        rows={credentialsQuery.data}
        isLoading={credentialsQuery.isLoading}
        isError={credentialsQuery.isError}
        error={credentialsQuery.error}
        onRetry={() => void credentialsQuery.refetch()}
        empty="No instance provider keys yet. Add one to give organizations a default provider account."
      />

      {canCreate && canReadCatalog && (
        <AddProviderCredentialDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          providers={providers}
          onSubmit={(values) => addCredential.mutateAsync({ data: values })}
          pending={addCredential.isPending}
        />
      )}
    </PageShell>
  );
}
