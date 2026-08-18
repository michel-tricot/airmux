import { useState } from 'react';
import * as z from 'zod';
import { Card, Button, Input, Badge, ConfirmButton, Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/elements';
import { Building2, Plus, ArrowLeft, Key, TerminalSquare, Users, Pencil, Trash2 } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link, useLocation } from 'wouter';
import { useOrg, useRenameOrgMutation, useDeleteOrgMutation } from '@/features/orgs/hooks';
import { useUsers, useAddUserToOrgMutation, useRemoveUserFromOrgMutation, orgRoleOptions } from '@/features/users/hooks';
import { useWorkspaces, useCreateWorkspaceMutation } from '@/features/workspaces/hooks';
import { useOrgAccessKeys, useRevokeOrgAccessKeyMutation } from '@/features/keys/hooks';
import { useOrgMembers } from '@/features/members/hooks';
import { LoadingState, ErrorState } from '@/components/shared/states';
import { DataTable } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { MembersPanel } from '@/components/shared/members-panel';
import { ApiKeysTable } from '@/components/shared/api-keys-table';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { useRequiredParam } from '@/lib/route';
import { PageShell } from '@/components/shared/page-shell';
import type { OrgRole } from '@workspace/api-client-react';
import { hasPermission, useEffectivePermissions } from '@/features/permissions/hooks';

const nameSchema = z.object({ name: z.string().min(1, 'Name is required') });

export default function OrganizationDetail() {
  const orgId = useRequiredParam('orgId');
  const [, setLocation] = useLocation();

  const orgQuery = useOrg(orgId);
  const org = orgQuery.data;
  const permissionsQuery = useEffectivePermissions({ orgId });
  const permissions = permissionsQuery.data?.permissions;
  const canCreateWorkspace = hasPermission(permissions, 'workspaces.create');
  const canReadKeys = hasPermission(permissions, 'access-keys.read');
  const canRevokeKeys = hasPermission(permissions, 'access-keys.revoke');
  const canReadMembers = hasPermission(permissions, 'members.read');
  const canManageMembers = hasPermission(permissions, 'members.manage');
  const canUpdate = hasPermission(permissions, 'organizations.update');
  const canDelete = hasPermission(permissions, 'organizations.delete');

  const workspacesQuery = useWorkspaces(orgId);
  const keysQuery = useOrgAccessKeys(orgId, undefined, canReadKeys);
  const membersQuery = useOrgMembers(orgId, canReadMembers);
  const usersQuery = useUsers();
  const users = usersQuery.data;
  const usersById = new Map(users?.map((user) => [user.id, user]));
  const members = membersQuery.data;
  const outsiders = users && members ? users.filter((user) => !members.some((member) => member.user_id === user.id)) : undefined;

  const [wsOpen, setWsOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);

  const createWorkspace = useCreateWorkspaceMutation(orgId);
  const revokeKey = useRevokeOrgAccessKeyMutation(orgId);
  const addMember = useAddUserToOrgMutation();
  const removeMember = useRemoveUserFromOrgMutation();
  const rename = useRenameOrgMutation();
  const deleteOrg = useDeleteOrgMutation();
  const defaultTab = canReadKeys ? 'keys' : canReadMembers ? 'members' : 'workspaces';

  if (orgQuery.isLoading) return <LoadingState label="Loading organization..." />;
  if (orgQuery.isError) return <ErrorState error={orgQuery.error} resource="organization" onRetry={() => orgQuery.refetch()} />;
  if (!org) return <ErrorState message="Organization not found" />;

  return (
    <PageShell>
      <div className="flex items-center gap-4 text-sm text-muted-foreground mb-4">
        <Link href="/instance/organizations" className="hover:text-foreground flex items-center gap-1">
          <ArrowLeft className="w-4 h-4" /> Back to Organizations
        </Link>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
            <Building2 className="w-6 h-6 text-primary" />
          </div>
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{org.name}</h1>
            <p className="text-muted-foreground font-mono text-sm">{org.id}</p>
          </div>
        </div>
        <div className="flex gap-2">
          {canUpdate && (
            <Button variant="outline" onClick={() => setRenameOpen(true)}>
              <Pencil className="w-4 h-4 mr-2" /> Rename
            </Button>
          )}
          {canDelete && (
            <ConfirmButton
              variant="outline"
              size="default"
              className="text-destructive hover:bg-destructive hover:text-destructive-foreground"
              title="Delete Organization"
              description={`This permanently deletes ${org.name}, its workspaces, keys, members, and policies. Usage already recorded remains on the organization’s bill.`}
              confirmLabel="Delete Organization"
              pending={deleteOrg.isPending}
              onConfirm={async () => {
                await deleteOrg.mutateAsync({ orgId: org.id });
                setLocation('/instance/organizations');
              }}
            >
              <Trash2 className="w-4 h-4 mr-2" /> Delete
            </ConfirmButton>
          )}
        </div>
      </div>

      <Tabs defaultValue={defaultTab} className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="workspaces" className="gap-2">
            <TerminalSquare className="w-4 h-4" /> Workspaces
          </TabsTrigger>
          {canReadKeys && (
            <TabsTrigger value="keys" className="gap-2">
              <Key className="w-4 h-4" /> Access Keys
            </TabsTrigger>
          )}
          {canReadMembers && (
            <TabsTrigger value="members" className="gap-2">
              <Users className="w-4 h-4" /> Members
            </TabsTrigger>
          )}
        </TabsList>

        <TabsContent value="workspaces" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Workspaces</h2>
            {canCreateWorkspace && (
              <Button onClick={() => setWsOpen(true)} size="sm">
                <Plus className="w-4 h-4 mr-1" /> New Workspace
              </Button>
            )}
          </div>
          <Card>
            <DataTable
              rows={workspacesQuery.data}
              rowKey={(ws) => ws.id}
              isLoading={workspacesQuery.isLoading}
              isError={workspacesQuery.isError}
              error={workspacesQuery.error}
              resource="workspaces"
              onRetry={() => workspacesQuery.refetch()}
              empty="No workspaces yet."
              columns={[
                {
                  key: 'name',
                  header: 'Name',
                  cellClassName: 'font-medium',
                  cell: (ws) => (
                    <Link href={`/instance/organizations/${org.id}/workspaces/${ws.slug}`} className="hover:text-primary transition-colors">
                      {ws.name}
                    </Link>
                  ),
                },
                { key: 'slug', header: 'Slug', cell: (ws) => <Badge variant="mono">{ws.slug}</Badge> },
                { key: 'id', header: 'Technical ID', cellClassName: 'font-mono text-xs text-muted-foreground', cell: (ws) => ws.id },
                {
                  key: 'created',
                  header: 'Created',
                  headClassName: 'text-right',
                  cellClassName: 'text-right text-muted-foreground text-sm',
                  cell: (ws) => formatDate(ws.created_at),
                },
              ]}
            />
          </Card>
        </TabsContent>

        {canReadKeys && (
          <TabsContent value="keys" className="space-y-4 mt-0">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-semibold">Access Keys</h2>
            </div>
            <ApiKeysTable
              keys={keysQuery.data}
              isLoading={keysQuery.isLoading}
              isError={keysQuery.isError}
              error={keysQuery.error}
              onRetry={() => keysQuery.refetch()}
              emptyText="No access keys for this organization."
              extraColumns={[
                {
                  key: 'user',
                  header: 'Principal',
                  cellClassName: 'text-muted-foreground text-sm',
                  cell: (key) => {
                    const user = usersById.get(key.user_id);
                    return user ? (
                      <Link href={`/instance/users/${user.id}`} className="hover:text-primary transition-colors">
                        {user.name}
                      </Link>
                    ) : (
                      key.user_id
                    );
                  },
                },
                { key: 'scope', header: 'Scope', cellClassName: 'text-muted-foreground text-sm', cell: (key) => key.scope.level },
              ]}
              revokeDescription="This key and every key delegated from it will stop working immediately."
              onRevoke={canRevokeKeys ? (key) => revokeKey.mutateAsync({ keyId: key.id }) : undefined}
              revokePending={canRevokeKeys ? revokeKey.isPending : undefined}
            />
          </TabsContent>
        )}

        {canReadMembers && (
          <TabsContent value="members" className="space-y-4 mt-0">
            <MembersPanel
              heading="Organization Members"
              members={members}
              isLoading={membersQuery.isLoading}
              isError={membersQuery.isError || usersQuery.isError}
              error={membersQuery.error ?? usersQuery.error}
              onRetry={() => Promise.all([membersQuery.refetch(), usersQuery.refetch()])}
              emptyText="No members yet."
              renderName={(member) => (
                <Link href={`/instance/users/${member.user_id}`} className="hover:text-primary">
                  {member.name}
                </Link>
              )}
              add={
                canManageMembers
                  ? {
                      candidates: outsiders?.map((user) => ({ value: user.id, label: `${user.name} (${user.email})` })) ?? [],
                      dialogTitle: 'Add Member',
                      placeholder: 'Select a user',
                      roles: orgRoleOptions,
                      defaultRole: 'member',
                      onAdd: (userId, role) => addMember.mutateAsync({ userId, orgId: org.id, role: role as OrgRole }),
                      pending: addMember.isPending || outsiders === undefined,
                    }
                  : undefined
              }
              remove={
                canManageMembers
                  ? {
                      title: (member) => `Remove ${member.name} from the organization?`,
                      description: 'They lose access to this organization and all of its workspaces.',
                      onRemove: (member) => removeMember.mutateAsync({ userId: member.user_id, orgId: org.id }),
                      pending: removeMember.isPending,
                    }
                  : undefined
              }
            />
          </TabsContent>
        )}
      </Tabs>

      {canCreateWorkspace && (
        <FormDialog
          open={wsOpen}
          onOpenChange={setWsOpen}
          title="New Workspace"
          schema={nameSchema}
          defaultValues={{ name: '' }}
          onSubmit={(values) => createWorkspace.mutateAsync({ orgId, data: values })}
          submitLabel="Create"
          pending={createWorkspace.isPending}
        >
          {(form) => (
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input placeholder="staging" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          )}
        </FormDialog>
      )}

      {canUpdate && (
        <FormDialog
          open={renameOpen}
          onOpenChange={setRenameOpen}
          title="Rename Organization"
          schema={nameSchema}
          defaultValues={{ name: org.name }}
          onSubmit={(values) => rename.mutateAsync({ orgId: org.id, data: values })}
          submitLabel="Save"
          pending={rename.isPending}
        >
          {(form) => (
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input {...field} />
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
