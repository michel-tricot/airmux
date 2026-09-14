import { useSession } from '@/lib/session';
import { useWorkspaceMembers } from '@/features/members/hooks';
import { workspaceMemberAccess } from '@/features/members/policy';
import { ErrorState } from '@/components/shared/states';
import { useState } from 'react';
import { Plus } from 'lucide-react';
import { Button } from '@/components/ui/elements';
import { ManagementKeyDialog } from '@/components/shared/management-key-dialog';
import { ManagementKeysTable } from '@/components/shared/management-keys-table';
import { SectionHeader } from '@/components/shared/page-shell';
import { useScopedAuthorization } from '@/features/permissions/hooks';
import { managementKeyAccess } from '@/features/keys/policy';
import { useWorkspaceManagementKeys, useCreateWorkspaceManagementKeyMutation, useRevokeWorkspaceManagementKeyMutation } from '@/features/keys/hooks';

export function WorkspaceManagementKeys({ orgId, workspaceId }: { orgId: string; workspaceId: string }) {
  const authorization = useScopedAuthorization({ level: 'workspace', orgId, workspaceRef: workspaceId });
  const { user } = useSession();
  const members = useWorkspaceMembers(orgId, workspaceId, { enabled: authorization.can(workspaceMemberAccess.read) });
  const canRead = authorization.can(managementKeyAccess.workspace.read);
  const canIssue = authorization.can(managementKeyAccess.workspace.issue);
  const canRevoke = authorization.can(managementKeyAccess.workspace.revoke);
  const keys = useWorkspaceManagementKeys(orgId, workspaceId, { enabled: canRead });
  const create = useCreateWorkspaceManagementKeyMutation();
  const revoke = useRevokeWorkspaceManagementKeyMutation(orgId, workspaceId);
  const [open, setOpen] = useState(false);
  return (
    <div className="space-y-4">
      <SectionHeader
        title="Management Keys"
        description="Control-plane API access limited to this workspace."
        actions={
          canIssue && (
            <Button size="sm" onClick={() => setOpen(true)}>
              <Plus className="size-4" />
              Generate Key
            </Button>
          )
        }
      />
      {members.isError && <ErrorState error={members.error} resource="key owners" onRetry={() => members.refetch()} />}
      <ManagementKeysTable
        owners={
          new Map<string, { name: string }>([
            ...(members.data ?? []).map((member) => [member.user_id, member] as const),
            ...(user ? [[user.user_id, user] as const] : []),
          ])
        }
        canEditPermissions={canIssue}
        resource="management keys"
        keys={keys.data}
        isLoading={keys.isLoading}
        isError={keys.isError}
        error={keys.error}
        onRetry={() => keys.refetch()}
        emptyText="No management keys for this workspace."
        revokeDescription="This management key and its delegated keys will stop working immediately."
        onRevoke={canRevoke ? (key) => revoke.mutateAsync({ keyId: key.id }) : undefined}
        revokePending={revoke.isPending}
      />
      {canIssue && (
        <ManagementKeyDialog
          open={open}
          onOpenChange={setOpen}
          title="Generate Management Key"
          description="This key can manage only this workspace. It cannot access other workspaces or make inference requests."
          availablePermissions={authorization.permissions}
          canIssue={canIssue}
          permissionsLoading={authorization.isFetching}
          permissionsError={authorization.error}
          onPermissionsRetry={() => authorization.refetch()}
          onSubmit={async (data) => (await create.mutateAsync({ orgId, workspaceRef: workspaceId, data })).token}
          pending={create.isPending}
          submitDisabled={authorization.isFetching || authorization.isError}
        />
      )}
    </div>
  );
}
