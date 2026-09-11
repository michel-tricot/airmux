import { useState } from 'react';
import * as z from 'zod';
import { Avatar, AvatarFallback, Card, Button, Dropdown, Badge, ConfirmButton } from '@/components/ui/elements';
import { ArrowLeft, Building2, KeyRound, Plus, UserMinus, Trash2 } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link, useLocation } from 'wouter';
import { useOrgs } from '@/features/orgs/hooks';
import { useInstanceManagementKeys } from '@/features/keys/hooks';
import {
  useUser,
  useChangeInstanceRoleMutation,
  useDeleteUserMutation,
  useAddUserToOrgMutation,
  useRemoveUserFromOrgMutation,
  orgRoleOptions,
} from '@/features/users/hooks';
import { LoadingState, ErrorState } from '@/components/shared/states';
import { DataTable } from '@/components/shared/data-table';
import { RoleSelect } from '@/components/shared/role-select';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { useRequiredParam } from '@/lib/route';
import { PageShell } from '@/components/shared/page-shell';
import { InstanceRole, type OrgOut, type OrgRole } from '@workspace/api-client-react';
import { useAuthorization } from '@/features/permissions/hooks';
import { managementKeyAccess } from '@/features/keys/policy';
import { orgMemberAccess } from '@/features/members/policy';
import { userAccess } from '@/features/users/policy';
import { AccountKindBadge } from '@/components/shared/account-display';
import { ManagementKeysTable } from '@/components/shared/management-keys-table';

const addToOrgSchema = z.object({
  orgId: z.string().min(1, 'Select an organization'),
  role: z.enum(['owner', 'admin', 'member', 'data_plane']),
});

export default function UserDetail() {
  const userId = useRequiredParam('userId');
  const [, setLocation] = useLocation();

  const userQuery = useUser(userId);
  const user = userQuery.data;
  const authorization = useAuthorization('instance');
  const canDeleteUser = authorization.can(userAccess.delete);
  const canAddMember = authorization.can(orgMemberAccess.add);
  const canRemoveMember = authorization.can(orgMemberAccess.remove);
  const canReadKeys = authorization.can(managementKeyAccess.instance.read);
  const orgsQuery = useOrgs();
  const orgs = orgsQuery.data;
  const managementKeysQuery = useInstanceManagementKeys({ user_id: userId }, { enabled: canReadKeys });

  const [addOpen, setAddOpen] = useState(false);
  const changeRole = useChangeInstanceRoleMutation();

  const addMember = useAddUserToOrgMutation();
  const removeMember = useRemoveUserFromOrgMutation();
  const deleteUser = useDeleteUserMutation();

  if (userQuery.isLoading) return <LoadingState label="Loading user..." />;
  if (userQuery.isError) return <ErrorState error={userQuery.error} resource="user" onRetry={() => userQuery.refetch()} />;
  if (!user) return <ErrorState message="User not found" />;

  const memberships = orgs?.filter((o) => user.orgs.includes(o.id));
  const available = orgs?.filter((o) => !user.orgs.includes(o.id));
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
              description="Their sign-in identities, sessions, and personal keys go with them. Users who still hold memberships, own a personal organization, or minted inference keys must be cleared first."
              confirmLabel="Delete User"
              pending={deleteUser.isPending}
              onConfirm={async () => {
                await deleteUser.mutateAsync({ userId: user.id });
                setLocation('/instance/users');
              }}
            >
              <Trash2 className="w-4 h-4 mr-2" /> Delete
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
          {canAddMember && (
            <Button onClick={() => setAddOpen(true)} size="sm" disabled={orgsQuery.isLoading || orgsQuery.isError || available?.length === 0}>
              <Plus className="w-4 h-4 mr-1" /> Add to Organization
            </Button>
          )}
        </div>
        <Card>
          <DataTable
            rows={memberships}
            rowKey={(org) => org.id}
            isLoading={orgsQuery.isLoading}
            isError={orgsQuery.isError}
            error={orgsQuery.error}
            resource="organizations"
            onRetry={() => orgsQuery.refetch()}
            empty="User does not belong to any organizations."
            columns={[
              {
                key: 'org',
                header: 'Organization',
                cellClassName: 'font-medium',
                cell: (org) => (
                  <Link href={`/instance/organizations/${org.id}`} className="hover:text-primary">
                    {org.name}
                  </Link>
                ),
              },
              { key: 'id', header: 'ID', cellClassName: 'font-mono text-xs text-muted-foreground', cell: (org) => org.id },
              { key: 'created', header: 'Created', cellClassName: 'text-muted-foreground text-sm', cell: (org) => formatDate(org.created_at) },
              ...(canRemoveMember
                ? [
                    {
                      key: 'actions',
                      header: 'Actions',
                      headClassName: 'text-right',
                      cellClassName: 'text-right',
                      cell: (org: OrgOut) => (
                        <ConfirmButton
                          title={`Remove ${user.name} from ${org.name}?`}
                          description="They lose access to this organization and all of its workspaces."
                          confirmLabel="Remove membership"
                          pending={removeMember.isPending}
                          aria-label="Remove membership"
                          onConfirm={() => removeMember.mutateAsync({ userId: user.id, orgId: org.id })}
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
      </div>

      {canReadKeys && (
        <div className="mt-8">
          <h2 className="text-lg font-semibold flex items-center gap-2 mb-4">
            <KeyRound className="w-5 h-5 text-muted-foreground" />
            Keys owned by this user
          </h2>

          <ManagementKeysTable
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

      {canAddMember && (
        <FormDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          title="Add to Organization"
          schema={addToOrgSchema}
          defaultValues={{ orgId: '', role: 'member' }}
          onSubmit={(values) => addMember.mutateAsync({ userId: user.id, orgId: values.orgId, role: values.role as OrgRole })}
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
    </PageShell>
  );
}
