import { useState } from 'react';
import * as z from 'zod';
import { Plus, RefreshCw, Power, Trash2 } from 'lucide-react';
import type { ProviderCredentialOut } from '@workspace/api-client-react';
import { useRequiredOrgId } from '@/lib/session';
import {
  useProviderCredentials,
  useProviders,
  useAddCredentialMutation,
  useRotateCredentialMutation,
  useUpdateCredentialMutation,
  useDeleteCredentialMutation,
} from '@/features/credentials/hooks';
import { Button, Input, ConfirmButton } from '@/components/ui/elements';
import { AddProviderCredentialDialog } from '@/components/shared/provider-credential-dialog';
import { ProviderCredentialsTable } from '@/components/shared/provider-credentials-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useRequiredParam } from '@/lib/route';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { ErrorState } from '@/components/shared/states';
import { useAuthorization } from '@/features/permissions/hooks';
import { catalogAccess } from '@/features/catalog/policy';
import { providerCredentialAccess } from '@/features/credentials/policy';

const rotateSchema = z.object({ value: z.string().min(1, 'Paste the replacement key') });

export default function WorkspaceByok() {
  const workspaceRef = useRequiredParam('workspaceRef');
  const orgId = useRequiredOrgId();

  const authorization = useAuthorization('workspace');
  const canRead = authorization.can(providerCredentialAccess.workspace.read);
  const canReadCatalog = authorization.can(catalogAccess.workspace.read);
  const canCreate = authorization.can(providerCredentialAccess.workspace.create);
  const canUpdate = authorization.can(providerCredentialAccess.update);
  const canRotate = authorization.can(providerCredentialAccess.rotate);
  const canDelete = authorization.can(providerCredentialAccess.delete);
  const canUseActions = canUpdate || canRotate || canDelete;
  const credentialsQuery = useProviderCredentials(orgId, workspaceRef, { enabled: canRead });
  const taxonomy = useProviders(orgId, workspaceRef, { enabled: canReadCatalog });
  const providers = taxonomy.data?.providers ?? [];

  const [addOpen, setAddOpen] = useState(false);
  const [rotating, setRotating] = useState<ProviderCredentialOut | null>(null);

  const addCredential = useAddCredentialMutation(orgId, workspaceRef);
  const rotateCredential = useRotateCredentialMutation(orgId, workspaceRef);
  const updateCredential = useUpdateCredentialMutation(orgId, workspaceRef);
  const deleteCredential = useDeleteCredentialMutation(orgId, workspaceRef);

  return (
    <PageShell>
      <PageHeader
        title="Provider Keys"
        description="Use your own API keys for this workspace. Keys are tried in priority order. If one fails, the next takes over automatically."
        actions={
          canCreate &&
          canReadCatalog && (
            <Button onClick={() => setAddOpen(true)} disabled={taxonomy.isLoading || taxonomy.isError || providers.length === 0}>
              <Plus className="w-4 h-4 mr-1" /> Add Key
            </Button>
          )
        }
      />

      {canReadCatalog && taxonomy.isError && <ErrorState error={taxonomy.error} resource="provider catalog" onRetry={() => taxonomy.refetch()} />}

      <ProviderCredentialsTable
        rows={credentialsQuery.data}
        isLoading={credentialsQuery.isLoading}
        isError={credentialsQuery.isError}
        error={credentialsQuery.error}
        onRetry={() => void credentialsQuery.refetch()}
        empty="No workspace keys configured. Requests use organization provider keys when available, then global provider keys."
        actions={
          canUseActions
            ? (credential) => (
                <div className="flex items-center gap-1">
                  {canRotate && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button aria-label={`Rotate ${credential.name}`} size="icon" variant="ghost" onClick={() => setRotating(credential)}>
                          <RefreshCw className="h-4 w-4" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Rotate key</TooltipContent>
                    </Tooltip>
                  )}

                  {canUpdate && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          size="icon"
                          variant="ghost"
                          aria-label={`${credential.enabled ? 'Disable' : 'Enable'} ${credential.name}`}
                          aria-pressed={credential.enabled}
                          className={credential.enabled ? '' : 'text-muted-foreground'}
                          onClick={() => updateCredential.mutate({ orgId, credentialId: credential.id, data: { enabled: !credential.enabled } })}
                        >
                          <Power className="h-4 w-4" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>{credential.enabled ? 'Disable' : 'Enable'}</TooltipContent>
                    </Tooltip>
                  )}

                  {canDelete && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span>
                          <ConfirmButton
                            title={`Delete "${credential.name}"?`}
                            description="Permanently removes this key. Traffic will fall back to the next available key in priority order. This cannot be undone."
                            confirmLabel="Delete"
                            pending={deleteCredential.isPending}
                            aria-label={`Delete ${credential.name}`}
                            onConfirm={() => deleteCredential.mutateAsync({ orgId, credentialId: credential.id })}
                          >
                            <Trash2 className="h-4 w-4" />
                          </ConfirmButton>
                        </span>
                      </TooltipTrigger>
                      <TooltipContent>Delete</TooltipContent>
                    </Tooltip>
                  )}
                </div>
              )
            : undefined
        }
      />

      {canCreate && canReadCatalog && (
        <AddProviderCredentialDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          providers={providers}
          onSubmit={(values) => addCredential.mutateAsync({ orgId, workspaceRef, data: values })}
          pending={addCredential.isPending}
        />
      )}

      {canRotate && (
        <FormDialog
          open={!!rotating}
          onOpenChange={(v) => !v && setRotating(null)}
          title={rotating ? `Rotate "${rotating.name}"` : 'Rotate'}
          description="Replaces the existing key immediately. Any in-flight requests will finish with the old key."
          schema={rotateSchema}
          defaultValues={{ value: '' }}
          onSubmit={async (values) => {
            if (!rotating) return;
            await rotateCredential.mutateAsync({ orgId, credentialId: rotating.id, data: values });
            setRotating(null);
          }}
          submitLabel="Rotate"
          pending={rotateCredential.isPending}
        >
          {(form) => (
            <FormField
              control={form.control}
              name="value"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>New API key</FormLabel>
                  <FormControl>
                    <Input type="password" autoComplete="off" placeholder="sk-..." {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          )}
        </FormDialog>
      )}
    </PageShell>
  );
}
