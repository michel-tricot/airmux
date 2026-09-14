import { useState } from 'react';
import { KeyRound, Plus } from 'lucide-react';
import { Button } from '@/components/ui/elements';
import { useInstanceManagementKeys, useCreateInstanceManagementKeyMutation, useRevokeInstanceManagementKeyMutation } from '@/features/keys/hooks';
import { useUsers } from '@/features/users/hooks';
import { ManagementKeyDialog } from '@/components/shared/management-key-dialog';
import { ManagementKeysTable } from '@/components/shared/management-keys-table';
import { ErrorState } from '@/components/shared/states';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { useAuthorization } from '@/features/permissions/hooks';
import { managementKeyAccess } from '@/features/keys/policy';
import { userAccess } from '@/features/users/policy';

export default function ManagementKeys() {
  const [createOpen, setCreateOpen] = useState(false);
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
        owners={usersById}
        ownerHref={(userId) => `/instance/users/${userId}`}
        canEditPermissions={authorization.can(managementKeyAccess.instance.updatePermissions)}
        resource="management keys"
        keys={keysQuery.data}
        isLoading={keysQuery.isLoading}
        isError={keysQuery.isError}
        error={keysQuery.error}
        onRetry={() => keysQuery.refetch()}
        emptyText="No management keys generated."
        revokeDescription="This key and every key delegated from it will stop working immediately."
        onRevoke={canRevoke ? (key) => revokeKey.mutateAsync({ keyId: key.id }) : undefined}
        revokePending={canRevoke ? revokeKey.isPending : undefined}
      />

      {canIssueKey && (
        <ManagementKeyDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          title="Generate Management Key"
          description="The key is bound to this instance. Its permission ceiling is stored as an explicit snapshot and the secret is shown only once."
          availablePermissions={authorization.permissions}
          canIssue={canIssueKey}
          permissionsLoading={authorization.isFetching}
          permissionsError={authorization.error}
          onPermissionsRetry={() => authorization.refetch()}
          onSubmit={async (data) => (await createKey.mutateAsync({ data })).token}
          pending={createKey.isPending}
          submitDisabled={authorization.isFetching || authorization.isError || !canIssueKey}
        />
      )}
    </PageShell>
  );
}
