import { useState } from 'react';
import * as z from 'zod';
import { Avatar, AvatarFallback, Card, Button, Dropdown, Badge, ConfirmButton } from '@/components/ui/elements';
import { ArrowLeft, Building2, KeyRound, Plus, UserMinus, Trash2, Blocks } from 'lucide-react';
import { Link, useLocation } from 'wouter';
import { useOrgs } from '@/features/orgs/hooks';
import { useInstanceManagementKeys } from '@/features/keys/hooks';
import { useWorkspaces } from '@/features/workspaces/hooks';
import {
  useUser,
  useUserMemberships,
  useChangeInstanceRoleMutation,
  useDeleteUserMutation,
  useAddUserToOrgMutation,
  useRemoveUserFromOrgMutation,
  useChangeOrgRoleMutation,
  orgRoleOptions,
} from '@/features/users/hooks';
import { LoadingState, ErrorState } from '@/components/shared/states';
import { DataTable } from '@/components/shared/data-table';
import { TableLink } from '@/components/shared/table-link';
import { RoleSelect } from '@/components/shared/role-select';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { useRequiredParam } from '@/lib/route';
import { PageShell } from '@/components/shared/page-shell';
import { InstanceRole, type OrgRoleAssignment } from '@workspace/api-client-react';
import { useAuthorization } from '@/features/permissions/hooks';
import { managementKeyAccess } from '@/features/keys/policy';
import { orgMemberAccess, workspaceMemberAccess } from '@/features/members/policy';
import { useChangeWorkspaceRoleMutation, workspaceRoleOptions } from '@/features/members/hooks';
import { userAccess } from '@/features/users/policy';
import { AccountKindBadge } from '@/components/shared/account-display';
import { ManagementKeysTable } from '@/components/shared/management-keys-table';

const addToOrgSchema = z.object({
  orgId: z.string().min(1, 'Select an organization'),
  role: z.enum(['owner', 'admin', 'member', 'data_plane']),
});

const addToWorkspaceSchema = z.object({
  orgId: z.string().min(1, 'Select an organization'),
  workspaceRef: z.string().min(1, 'Select a workspace'),
  role: z.enum(['admin', 'member', 'viewer']),
});

export default function UserDetail() {
  const userId = useRequiredParam('userId');
  const [, setLocation] = useLocation();

  const userQuery = useUser(userId);
  const user = userQuery.data;
  const membershipsQuery = useUserMemberships(userId);
  const memberships = membershipsQuery.data;
  const authorization = useAuthorization('instance');
  const canDeleteUser = authorization.can(userAccess.delete);
  const canAddMember = authorization.can(orgMemberAccess.add);
  const canRemoveMember = authorization.can(orgMemberAccess.remove);
  const canManageWorkspaceMember = authorization.can(workspaceMemberAccess.add);
  const canReadKeys = authorization.can(managementKeyAccess.instance.read);
  const orgsQuery = useOrgs({ enabled: canAddMember && !user?.managing_org_id });
  const orgs = orgsQuery.data;
  const managementKeysQuery = useInstanceManagementKeys({ user_id: userId }, { enabled: canReadKeys });

  const [addOpen, setAddOpen] = useState(false);
  const [addWorkspaceOpen, setAddWorkspaceOpen] = useState(false);
  const [selectedOrgId, setSelectedOrgId] = useState('');
  const workspacesQuery = useWorkspaces(selectedOrgId, { enabled: Boolean(selectedOrgId) && addWorkspaceOpen });
  const changeRole = useChangeInstanceRoleMutation();

  const addMember = useAddUserToOrgMutation();
  const removeMember = useRemoveUserFromOrgMutation();
  const changeOrgRole = useChangeOrgRoleMutation();
  const changeWorkspaceRole = useChangeWorkspaceRoleMutation();
  const deleteUser = useDeleteUserMutation();

  if (userQuery.isLoading) return <LoadingState label="Loading user..." />;
  if (userQuery.isError) return <ErrorState error={userQuery.error} resource="user" onRetry={() => userQuery.refetch()} />;
  if (!user) return <ErrorState message="User not found" />;
  if (membershipsQuery.isLoading) return <LoadingState label="Loading memberships..." />;
  if (membershipsQuery.isError)
    return <ErrorState error={membershipsQuery.error} resource="memberships" onRetry={() => membershipsQuery.refetch()} />;
  if (!memberships) return <ErrorState message="Memberships unavailable" />;

  const memberOrgIds = new Set(memberships.org_memberships.map((membership) => membership.org_id));
  const available = orgs?.filter((org) => !memberOrgIds.has(org.id));
  const availableWorkspaces = workspacesQuery.data?.filter(
    (workspace) => !memberships.workspace_memberships.some((membership) => membership.workspace_id === workspace.id),
  );
  return (
    <PageShell>
      <div className="flex items-center gap-4 text-sm text-muted-foreground mb-4">
        <Link href="/instance/users" className="hover:text-foreground flex items-center gap-1">
          <ArrowLeft className="w-4 h-4" /> Back to Users
        </Link>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <Avatar aria-hidden="true" className="h-16 w-16 shadow-lg">
            <AvatarFallback className="bg-primary text-2xl font-bold text-primary-foreground">{user.name.charAt(0)}</AvatarFallback>
          </Avatar>
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{user.name}</h1>
            <p className="text-muted-foreground text-sm">{user.email}</p>
            <p className="text-muted-foreground font-mono text-xs mt-1">{user.id}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <AccountKindBadge serviceAccount={user.service_account} />
          {authorization.can(userAccess.changeRole) && !user.managing_org_id ? (
            <RoleSelect
              value={user.instance_role ?? 'none'}
              label="Instance role"
              name={user.name}
              options={[
                { value: 'none', label: 'No instance role' },
                { value: 'owner', label: 'Owner' },
                { value: 'auditor', label: 'Auditor' },
                { value: 'data_plane', label: 'Data plane' },
              ]}
              pending={changeRole.isPending}
              onSave={(role) =>
                changeRole.mutateAsync({ userId: user.id, data: { instance_role: role === 'none' ? null : z.nativeEnum(InstanceRole).parse(role) } })
              }
            />
          ) : (
            <Badge variant="secondary">{user.instance_role ?? 'No instance role'}</Badge>
          )}
          {canDeleteUser && (
            <ConfirmButton
              variant="outline"
              size="default"
              className="text-destructive hover:bg-destructive hover:text-destructive-foreground"
              title="Delete User"
              description="Their sign-in identities, sessions, and personal keys go with them. Users who still hold memberships, own a personal organization, or created inference keys must be cleared first."
              confirmLabel="Delete User"
              pending={deleteUser.isPending}
              onConfirm={async () => {
                await deleteUser.mutateAsync({ userId: user.id });
                setLocation('/instance/users');
              }}
            >
              <Trash2 className="w-4 h-4" /> Delete
            </ConfirmButton>
          )}
        </div>
      </div>

      <div className="mt-8">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Building2 className="w-5 h-5 text-muted-foreground" />
            Organization Memberships
          </h2>
          {canAddMember && !user.managing_org_id && (
            <Button onClick={() => setAddOpen(true)} size="sm" disabled={orgsQuery.isLoading || orgsQuery.isError || available?.length === 0}>
              <Plus className="w-4 h-4" /> Add to Organization
            </Button>
          )}
        </div>
        <Card>
          <DataTable
            rows={memberships.org_memberships}
            rowKey={(membership) => membership.org_id}
            resource="organization memberships"
            empty="User does not belong to any organizations."
            columns={[
              {
                key: 'org',
                header: 'Organization',
                cellClassName: 'font-medium',
                cell: (membership) => <TableLink href={`/instance/organizations/${membership.org_id}`}>{membership.name}</TableLink>,
              },
              {
                key: 'role',
                header: 'Role',
                cell: (membership) =>
                  canAddMember ? (
                    <RoleSelect
                      value={membership.role}
                      label={`Organization role in ${membership.name}`}
                      name={user.name}
                      options={user.managing_org_id ? orgRoleOptions.filter((option) => option.value !== 'owner') : orgRoleOptions}
                      pending={changeOrgRole.isPending}
                      onSave={(role) => changeOrgRole.mutateAsync({ userId: user.id, orgId: membership.org_id, role })}
                    />
                  ) : (
                    membership.role
                  ),
              },
              ...(canRemoveMember
                ? [
                    {
                      key: 'actions',
                      header: 'Actions',
                      headClassName: 'text-right',
                      cellClassName: 'text-right',
                      cell: (membership: OrgRoleAssignment) =>
                        user.managing_org_id === membership.org_id ? null : (
                          <ConfirmButton
                            title={`Remove ${user.name} from ${membership.name}?`}
                            description="They lose access to this organization, and their inference keys and playground sessions across it stop working immediately."
                            confirmLabel="Remove membership"
                            pending={removeMember.isPending}
                            aria-label="Remove membership"
                            onConfirm={() => removeMember.mutateAsync({ userId: user.id, orgId: membership.org_id })}
                          >
                            <UserMinus className="w-4 h-4" />
                          </ConfirmButton>
                        ),
                    },
                  ]
                : []),
            ]}
          />
        </Card>
        {canAddMember && orgsQuery.isError && (
          <ErrorState error={orgsQuery.error} message="Organizations are unavailable for new memberships." onRetry={() => orgsQuery.refetch()} />
        )}
      </div>

      <div className="mt-8">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Blocks className="w-5 h-5 text-muted-foreground" /> Workspace Memberships
          </h2>
          {canManageWorkspaceMember && (
            <Button onClick={() => setAddWorkspaceOpen(true)} size="sm" disabled={memberships.org_memberships.length === 0}>
              <Plus className="w-4 h-4" /> Add to Workspace
            </Button>
          )}
        </div>
        <p className="text-sm text-muted-foreground mb-4">
          Direct workspace roles are shown below. Instance and organization roles can also grant access.
        </p>
        <Card>
          <DataTable
            rows={memberships.workspace_memberships}
            rowKey={(membership) => membership.workspace_id}
            resource="workspace memberships"
            empty="User does not belong to any workspaces."
            columns={[
              {
                key: 'workspace',
                header: 'Workspace',
                cell: (membership) => (
                  <TableLink href={`/instance/organizations/${membership.org_id}/workspaces/${membership.slug}`}>{membership.name}</TableLink>
                ),
              },
              {
                key: 'organization',
                header: 'Organization',
                cell: (membership) => memberships.org_memberships.find((org) => org.org_id === membership.org_id)?.name ?? membership.org_id,
              },
              {
                key: 'role',
                header: 'Role',
                cell: (membership) =>
                  canManageWorkspaceMember ? (
                    <RoleSelect
                      value={membership.role}
                      label={`Workspace role in ${membership.name}`}
                      name={user.name}
                      options={workspaceRoleOptions}
                      pending={changeWorkspaceRole.isPending}
                      onSave={(role) =>
                        changeWorkspaceRole.mutateAsync({ userId: user.id, orgId: membership.org_id, workspaceRef: membership.slug, data: { role } })
                      }
                    />
                  ) : (
                    membership.role
                  ),
              },
            ]}
          />
        </Card>
      </div>

      {canReadKeys && (
        <div className="mt-8">
          <h2 className="text-lg font-semibold flex items-center gap-2 mb-4">
            <KeyRound className="w-5 h-5 text-muted-foreground" />
            Keys owned by this user
          </h2>

          <ManagementKeysTable
            owners={new Map([[user.id, user]])}
            canEditPermissions={authorization.can(managementKeyAccess.instance.updatePermissions)}
            resource="management keys"
            keys={managementKeysQuery.data}
            isLoading={managementKeysQuery.isLoading}
            isError={managementKeysQuery.isError}
            error={managementKeysQuery.error}
            onRetry={() => managementKeysQuery.refetch()}
            emptyText="This user does not own any management keys."
          />
        </div>
      )}

      {canAddMember && !user.managing_org_id && (
        <FormDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          title="Add to Organization"
          schema={addToOrgSchema}
          defaultValues={{ orgId: '', role: 'member' }}
          onSubmit={(values) => {
            const role = orgRoleOptions.find((option) => option.value === values.role);
            if (!role) throw new Error('Selected role is unavailable');
            return addMember.mutateAsync({ userId: user.id, orgId: values.orgId, role: role.value });
          }}
          submitLabel="Add"
          pending={addMember.isPending}
        >
          {(form) => (
            <>
              <FormField
                control={form.control}
                name="orgId"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Organization</FormLabel>
                    <FormControl>
                      <Dropdown
                        aria-label="Organization"
                        value={field.value}
                        onValueChange={field.onChange}
                        placeholder="Select an organization"
                        options={(available ?? []).map((org) => ({ value: org.id, label: org.name }))}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="role"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Role</FormLabel>
                    <FormControl>
                      <Dropdown aria-label="Role" value={field.value} onValueChange={field.onChange} options={orgRoleOptions} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </>
          )}
        </FormDialog>
      )}
      {canManageWorkspaceMember && (
        <FormDialog
          open={addWorkspaceOpen}
          onOpenChange={(open) => {
            setAddWorkspaceOpen(open);
            if (!open) setSelectedOrgId('');
          }}
          title="Add to Workspace"
          schema={addToWorkspaceSchema}
          defaultValues={{ orgId: '', workspaceRef: '', role: 'member' }}
          onSubmit={(values) => {
            const role = workspaceRoleOptions.find((option) => option.value === values.role);
            if (!role) throw new Error('Selected role is unavailable');
            return changeWorkspaceRole.mutateAsync({
              userId: user.id,
              orgId: values.orgId,
              workspaceRef: values.workspaceRef,
              data: { role: role.value },
            });
          }}
          submitLabel="Add"
          pending={changeWorkspaceRole.isPending}
        >
          {(form) => (
            <>
              <FormField
                control={form.control}
                name="orgId"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Organization</FormLabel>
                    <FormControl>
                      <Dropdown
                        aria-label="Organization"
                        value={field.value}
                        onValueChange={(orgId) => {
                          field.onChange(orgId);
                          form.setValue('workspaceRef', '');
                          setSelectedOrgId(orgId);
                        }}
                        placeholder="Select an organization"
                        options={memberships.org_memberships.map((membership) => ({ value: membership.org_id, label: membership.name }))}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="workspaceRef"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Workspace</FormLabel>
                    <FormControl>
                      <Dropdown
                        aria-label="Workspace"
                        value={field.value}
                        onValueChange={field.onChange}
                        placeholder="Select a workspace"
                        disabled={!selectedOrgId || workspacesQuery.isLoading || workspacesQuery.isError}
                        options={(availableWorkspaces ?? []).map((workspace) => ({ value: workspace.slug, label: workspace.name }))}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {workspacesQuery.isError && (
                <ErrorState error={workspacesQuery.error} resource="workspaces" onRetry={() => workspacesQuery.refetch()} />
              )}
              {selectedOrgId && availableWorkspaces?.length === 0 && (
                <p className="text-sm text-muted-foreground">No additional workspaces are available in this organization.</p>
              )}
              <FormField
                control={form.control}
                name="role"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Role</FormLabel>
                    <FormControl>
                      <Dropdown aria-label="Role" value={field.value} onValueChange={field.onChange} options={workspaceRoleOptions} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </>
          )}
        </FormDialog>
      )}
    </PageShell>
  );
}
