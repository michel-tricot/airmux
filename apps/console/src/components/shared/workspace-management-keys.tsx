import { useState } from 'react';
import { Plus } from 'lucide-react';
import { Button } from '@/components/ui/elements';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { ManagementKeyFormFields, managementKeyFormSchema } from '@/components/shared/management-key-form';
import { ManagementKeyPermissionsCell } from '@/components/shared/management-key-permissions-cell';
import { KeysTable } from '@/components/shared/keys-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { SectionHeader } from '@/components/shared/page-shell';
import { useScopedAuthorization } from '@/features/permissions/hooks';
import { managementKeyAccess } from '@/features/keys/policy';
import { useWorkspaceManagementKeys, useCreateWorkspaceManagementKeyMutation, useRevokeWorkspaceManagementKeyMutation } from '@/features/keys/hooks';

export function WorkspaceManagementKeys({ orgId, workspaceId }: { orgId: string; workspaceId: string }) {
  const authorization = useScopedAuthorization({ level: 'workspace', orgId, workspaceRef: workspaceId });
  const canRead = authorization.can(managementKeyAccess.workspace.read);
  const canIssue = authorization.can(managementKeyAccess.workspace.issue);
  const canRevoke = authorization.can(managementKeyAccess.workspace.revoke);
  const keys = useWorkspaceManagementKeys(orgId, workspaceId, { enabled: canRead });
  const create = useCreateWorkspaceManagementKeyMutation();
  const revoke = useRevokeWorkspaceManagementKeyMutation(orgId, workspaceId);
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  return (
    <div className="space-y-4">
      <SectionHeader
        title="Management Keys"
        description="Control-plane API access limited to this workspace."
        actions={
          canIssue && (
            <Button size="sm" onClick={() => setOpen(true)}>
              <Plus className="mr-1 size-4" />
              Generate Key
            </Button>
          )
        }
      />
      <KeysTable
        resource="management keys"
        keys={keys.data}
        isLoading={keys.isLoading}
        isError={keys.isError}
        error={keys.error}
        onRetry={() => keys.refetch()}
        emptyText="No management keys for this workspace."
        extraColumns={[
          { key: 'permissions', header: 'Permissions', cell: (key) => <ManagementKeyPermissionsCell apiKey={key} canEdit={canIssue} /> },
        ]}
        revokeDescription="This management key and its delegated keys will stop working immediately."
        onRevoke={canRevoke ? (key) => revoke.mutateAsync({ keyId: key.id }) : undefined}
        revokePending={revoke.isPending}
      />
      {canIssue && (
        <FormDialog
          open={open}
          onOpenChange={setOpen}
          title="Generate Management Key"
          description="This key can manage only this workspace. It cannot access other workspaces or make inference requests."
          schema={managementKeyFormSchema}
          defaultValues={{ label: '', permissions: [] }}
          onSubmit={async (data) => {
            const key = await create.mutateAsync({ orgId, workspaceRef: workspaceId, data });
            setToken(key.token);
          }}
          submitLabel="Generate"
          pending={create.isPending}
          submitDisabled={authorization.isFetching || authorization.isError}
        >
          {(form) => (
            <ManagementKeyFormFields
              form={form}
              availablePermissions={authorization.permissions}
              canIssue={canIssue}
              permissionsLoading={authorization.isFetching}
              permissionsError={authorization.error}
              onPermissionsRetry={() => authorization.refetch()}
            />
          )}
        </FormDialog>
      )}
      <KeyRevealDialog open={token !== null} onOpenChange={(open) => !open && setToken(null)} token={token} />
    </div>
  );
}
