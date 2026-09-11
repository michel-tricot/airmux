import { useState } from 'react';
import { KeyRound, Plus } from 'lucide-react';
import { Badge, Button } from '@/components/ui/elements';
import { useInstanceManagementKeys, useCreateInstanceManagementKeyMutation, useRevokeInstanceManagementKeyMutation } from '@/features/keys/hooks';
import { useUsers } from '@/features/users/hooks';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { ManagementKeyFormFields, managementKeyFormSchema } from '@/components/shared/management-key-form';
import { ManagementKeyPermissionsCell } from '@/components/shared/management-key-permissions-cell';
import { KeysTable } from '@/components/shared/keys-table';
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

      <KeysTable
        compact
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
            headClassName: 'w-[13%]',
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
          {
            key: 'scope',
            header: 'Scope',
            headClassName: 'w-[10%]',
            cell: (key) => <Badge variant="secondary">{key.scope.level}</Badge>,
          },
          {
            key: 'target',
            header: 'Target',
            headClassName: 'w-[9%]',
            cellClassName: 'font-mono text-xs text-muted-foreground',
            cell: (key) => {
              const target = key.scope.workspace_id ?? key.scope.org_id;
              return (
                <span className="block truncate" title={target ?? undefined}>
                  {target ? `${target.slice(0, 8)}…` : 'instance'}
                </span>
              );
            },
          },
          {
            key: 'permissions',
            header: 'Permissions',
            headClassName: 'w-[20%]',
            cell: (key) => (
              <ManagementKeyPermissionsCell compact apiKey={key} canEdit={authorization.can(managementKeyAccess.instance.updatePermissions)} />
            ),
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
          defaultValues={{ label: '', permissions: [] }}
          onSubmit={async (values) => {
            const minted = await createKey.mutateAsync({ data: { label: values.label, permissions: values.permissions } });
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
