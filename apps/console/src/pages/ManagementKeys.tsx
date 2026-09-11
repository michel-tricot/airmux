import { useState } from 'react';
import { KeyRound, Plus } from 'lucide-react';
import { Button } from '@/components/ui/elements';
import { useInstanceManagementKeys, useCreateInstanceManagementKeyMutation, useRevokeInstanceManagementKeyMutation } from '@/features/keys/hooks';
import { useUsers } from '@/features/users/hooks';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { ManagementKeyFormFields, managementKeyPayload, managementKeyFormSchema } from '@/components/shared/management-key-form';
import { ManagementKeysTable } from '@/components/shared/management-keys-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { ErrorState } from '@/components/shared/states';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { useAuthorization } from '@/features/permissions/hooks';
import { managementKeyAccess } from '@/features/keys/policy';
import { userAccess } from '@/features/users/policy';
import { AccountIdentity } from '@/components/shared/account-display';

export default function ManagementKeys() {
  const [createOpen, setCreateOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const authorization = useAuthorization('instance');
  const canRead = authorization.can(managementKeyAccess.instance.read);
  const canIssueKey = authorization.can(managementKeyAccess.instance.issue);
  const canRevoke = authorization.can(managementKeyAccess.instance.revoke);
  const canReadUsers = authorization.can(userAccess.list);
  const keysQuery = useInstanceManagementKeys(undefined, { enabled: canRead });
  const usersQuery = useUsers({ enabled: canReadUsers });
  const usersById = new Map(usersQuery.data?.map((user) => [user.id, user]));
  const createKey = useCreateInstanceManagementKeyMutation();
  const revokeKey = useRevokeInstanceManagementKeyMutation();

  return (
    <PageShell>
      <PageHeader
        title="Management Keys"
        description="Management keys grant control-plane API access limited by principal, tenant scope, and explicit permissions."
        icon={KeyRound}
        actions={
          canIssueKey && (
            <Button onClick={() => setCreateOpen(true)} className="gap-2">
              <Plus className="h-4 w-4" /> Generate Key
            </Button>
          )
        }
      />

      {canReadUsers && usersQuery.isError && <ErrorState error={usersQuery.error} resource="key principals" onRetry={() => usersQuery.refetch()} />}

      <ManagementKeysTable
        canEditPermissions={authorization.can(managementKeyAccess.instance.updatePermissions)}
        resource="management keys"
        keys={keysQuery.data}
        isLoading={keysQuery.isLoading}
        isError={keysQuery.isError}
        error={keysQuery.error}
        onRetry={() => keysQuery.refetch()}
        emptyText="No management keys generated."
        extraColumns={[
          {
            key: 'principal',
            header: 'Principal',
            cellClassName: 'text-sm',
            cell: (key) => {
              const user = usersById.get(key.user_id);
              return user ? (
                <AccountIdentity name={user.name} href={`/instance/users/${user.id}`} />
              ) : (
                <span className="font-mono text-xs text-muted-foreground">{key.user_id}</span>
              );
            },
          },
        ]}
        revokeDescription="This key and every key delegated from it will stop working immediately."
        onRevoke={canRevoke ? (key) => revokeKey.mutateAsync({ keyId: key.id }) : undefined}
        revokePending={canRevoke ? revokeKey.isPending : undefined}
      />

      {canIssueKey && (
        <FormDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          title="Generate Management Key"
          description="The key is bound to this instance. Its permission ceiling is stored as an explicit snapshot and the secret is shown only once."
          schema={managementKeyFormSchema}
          defaultValues={{ label: '', permissions: [], expiry: 'never' }}
          onSubmit={async (values) => {
            const minted = await createKey.mutateAsync({ data: managementKeyPayload(values) });
            setToken(minted.token);
          }}
          submitLabel="Generate"
          pendingLabel="Generating..."
          pending={createKey.isPending}
          submitDisabled={authorization.isFetching || authorization.isError || !canIssueKey}
        >
          {(form) => (
            <ManagementKeyFormFields
              form={form}
              availablePermissions={authorization.permissions}
              canIssue={canIssueKey}
              permissionsLoading={authorization.isFetching}
            />
          )}
        </FormDialog>
      )}

      <KeyRevealDialog open={!!token} onOpenChange={(open) => !open && setToken(null)} token={token} />
    </PageShell>
  );
}
