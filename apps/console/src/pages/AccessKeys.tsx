import { useState } from 'react';
import { KeyRound, Plus } from 'lucide-react';
import { Link } from 'wouter';
import { Badge, Button } from '@/components/ui/elements';
import {
  useInstanceAccessKeys,
  useCreateInstanceAccessKeyMutation,
  useRevokeInstanceAccessKeyMutation,
  useGrantablePermissions,
} from '@/features/keys/hooks';
import { useUsers } from '@/features/users/hooks';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { AccessKeyFormFields, accessKeyFormSchema, canIssueAccessKeys } from '@/components/shared/access-key-form';
import { PermissionsCell } from '@/components/shared/permissions-cell';
import { ApiKeysTable } from '@/components/shared/api-keys-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { ErrorState } from '@/components/shared/states';
import { PageShell } from '@/components/shared/page-shell';

export default function AccessKeys() {
  const [createOpen, setCreateOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const keysQuery = useInstanceAccessKeys();
  const usersQuery = useUsers();
  const usersById = new Map(usersQuery.data?.map((user) => [user.id, user]));
  const createKey = useCreateInstanceAccessKeyMutation();
  const permissionsQuery = useGrantablePermissions({ enabled: createOpen });
  const canIssueKey = canIssueAccessKeys(permissionsQuery.data?.permissions);
  const revokeKey = useRevokeInstanceAccessKeyMutation();

  return (
    <PageShell>
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <div className="flex items-center gap-3">
            <KeyRound className="h-6 w-6 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight">Access Keys</h1>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">Credentials limited by principal, tenant scope, and explicit permissions.</p>
        </div>
        <Button onClick={() => setCreateOpen(true)} className="gap-2">
          <Plus className="h-4 w-4" /> Mint Access Key
        </Button>
      </div>

      {usersQuery.isError && <ErrorState error={usersQuery.error} resource="key principals" onRetry={() => usersQuery.refetch()} />}

      <ApiKeysTable
        keys={keysQuery.data}
        isLoading={keysQuery.isLoading}
        isError={keysQuery.isError}
        error={keysQuery.error}
        onRetry={() => keysQuery.refetch()}
        emptyText="No access keys have been minted."
        extraColumns={[
          {
            key: 'principal',
            header: 'Principal',
            cellClassName: 'text-sm',
            cell: (key) => {
              const user = usersById.get(key.user_id);
              return user ? (
                <Link href={`/instance/users/${user.id}`} className="transition-colors hover:text-primary">
                  {user.name}
                </Link>
              ) : (
                <span className="font-mono text-xs text-muted-foreground">{key.user_id}</span>
              );
            },
          },
          {
            key: 'scope',
            header: 'Scope',
            cell: (key) => <Badge variant="secondary">{key.scope.level}</Badge>,
          },
          {
            key: 'target',
            header: 'Target',
            cellClassName: 'font-mono text-xs text-muted-foreground',
            cell: (key) => key.scope.workspace_id ?? key.scope.org_id ?? 'instance',
          },
          {
            key: 'permissions',
            header: 'Permissions',
            cell: (key) => <PermissionsCell permissions={key.permissions} />,
          },
        ]}
        revokeDescription="This key and every key delegated from it will stop working immediately."
        onRevoke={(key) => revokeKey.mutateAsync({ keyId: key.id })}
        revokePending={revokeKey.isPending}
      />

      <FormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="Mint an instance access key"
        description="The key is bound to this instance. Its permission ceiling is stored as an explicit snapshot and the secret is shown only once."
        schema={accessKeyFormSchema}
        defaultValues={{ label: '', permissions: [] }}
        onSubmit={async (values) => {
          const minted = await createKey.mutateAsync({ data: { label: values.label, permissions: values.permissions } });
          setToken(minted.token);
        }}
        submitLabel="Mint key"
        pendingLabel="Minting..."
        pending={createKey.isPending}
        submitDisabled={permissionsQuery.isFetching || permissionsQuery.isError || !canIssueKey}
      >
        {(form) => (
          <AccessKeyFormFields
            form={form}
            availablePermissions={permissionsQuery.data?.permissions ?? []}
            permissionsLoading={permissionsQuery.isFetching}
            permissionsError={permissionsQuery.isError ? permissionsQuery.error : undefined}
            onPermissionsRetry={() => void permissionsQuery.refetch()}
          />
        )}
      </FormDialog>

      <KeyRevealDialog open={!!token} onOpenChange={(open) => !open && setToken(null)} token={token} />
    </PageShell>
  );
}
