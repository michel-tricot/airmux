import { useState } from 'react';
import * as z from 'zod';
import { useRequiredOrgId } from '@/lib/session';
import { useInferenceKeys, useCreateInferenceKeyMutation, useRevokeInferenceKeyMutation } from '@/features/keys/hooks';
import { Button, Input } from '@/components/ui/elements';
import { Plus } from 'lucide-react';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { FormDialog } from '@/components/shared/form-dialog';
import { ApiKeysTable } from '@/components/shared/api-keys-table';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { useRequiredParam } from '@/lib/route';
import { PageShell } from '@/components/shared/page-shell';
import { ErrorState, LoadingState } from '@/components/shared/states';
import { useAuthorization } from '@/features/permissions/hooks';
import { inferenceKeyAccess } from '@/features/keys/policy';

const keyLabelSchema = z.object({ label: z.string().min(1, 'Label is required') });

export default function WorkspaceApiKeys() {
  const workspaceRef = useRequiredParam('workspaceRef');
  const orgId = useRequiredOrgId();

  const authorization = useAuthorization('workspace');
  const canRead = authorization.can(inferenceKeyAccess.read);
  const canCreate = authorization.can(inferenceKeyAccess.create);
  const canRevoke = authorization.can(inferenceKeyAccess.revoke);
  const keysQuery = useInferenceKeys(orgId, workspaceRef, canRead);

  const [keyOpen, setKeyOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);

  const createKey = useCreateInferenceKeyMutation(orgId, workspaceRef);
  const revokeKey = useRevokeInferenceKeyMutation(orgId, workspaceRef);

  if (authorization.isLoading) return <LoadingState label="Loading workspace permissions..." />;
  if (authorization.isError)
    return <ErrorState error={authorization.error} resource="workspace permissions" onRetry={() => authorization.refetch()} />;
  if (!canRead) return <ErrorState message="You do not have access to inference keys in this workspace." />;

  return (
    <PageShell>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">API Keys</h1>
          <p className="text-muted-foreground mt-1 text-sm">Keys let applications send requests to the models available to this workspace.</p>
        </div>
        {canCreate && (
          <Button onClick={() => setKeyOpen(true)}>
            <Plus className="w-4 h-4 mr-1" /> Generate Key
          </Button>
        )}
      </div>

      <ApiKeysTable
        keys={keysQuery.data}
        isLoading={keysQuery.isLoading}
        isError={keysQuery.isError}
        error={keysQuery.error}
        onRetry={() => keysQuery.refetch()}
        emptyText="No inference keys generated."
        revokeDescription="Requests using this inference key will stop working immediately. This cannot be undone."
        onRevoke={canRevoke ? (key) => revokeKey.mutateAsync({ orgId, workspaceRef, keyId: key.id }) : undefined}
        revokePending={canRevoke ? revokeKey.isPending : undefined}
      />

      {canCreate && (
        <FormDialog
          open={keyOpen}
          onOpenChange={setKeyOpen}
          title="Generate Inference Key"
          description="Keys let applications send requests to the models available to this workspace."
          schema={keyLabelSchema}
          defaultValues={{ label: '' }}
          onSubmit={async (values) => {
            const minted = await createKey.mutateAsync({ orgId, workspaceRef, data: values });
            setToken(minted.token);
          }}
          submitLabel="Generate"
          pending={createKey.isPending}
        >
          {(form) => (
            <FormField
              control={form.control}
              name="label"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Label</FormLabel>
                  <FormControl>
                    <Input placeholder="e.g. chatbot-prod" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          )}
        </FormDialog>
      )}

      <KeyRevealDialog open={!!token} onOpenChange={(v) => !v && setToken(null)} token={token} />
    </PageShell>
  );
}
