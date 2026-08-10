import { useState } from 'react';
import * as z from 'zod';
import { Card, Button, Input, Modal, Badge, Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/elements';
import { Building2, Plus, ArrowLeft, Key, TerminalSquare, Users, Pencil, Trash2, ShieldAlert } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link, useParams, useLocation } from 'wouter';
import { useOrg, useRenameOrgMutation, useDeleteOrgMutation } from '@/features/orgs/hooks';
import { useUsers, useAddUserToOrgMutation, useRemoveUserFromOrgMutation } from '@/features/users/hooks';
import { useWorkspaces, useCreateWorkspaceMutation } from '@/features/workspaces/hooks';
import { useManagementKeys, useRevokeManagementKeyMutation } from '@/features/keys/hooks';
import { useOrgMembers } from '@/features/members/hooks';
import { LoadingState, ErrorState } from '@/components/shared/states';
import { DataTable } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { MembersPanel } from '@/components/shared/members-panel';
import { ApiKeysTable } from '@/components/shared/api-keys-table';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';

const nameSchema = z.object({ name: z.string().min(1, 'Name is required') });

export default function OrganizationDetail() {
  const { orgId } = useParams();
  const [, setLocation] = useLocation();

  const { data: org, isLoading } = useOrg(orgId!);

  const workspacesQuery = useWorkspaces(orgId!);
  const keysQuery = useManagementKeys(orgId!);
  const membersQuery = useOrgMembers(orgId!);
  const { data: users } = useUsers();
  const members = membersQuery.data;
  const outsiders = users?.filter(u => !members?.some(m => m.user_id === u.id));

  const [wsOpen, setWsOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const createWorkspace = useCreateWorkspaceMutation(orgId!);
  const revokeKey = useRevokeManagementKeyMutation(orgId!);
  const addMember = useAddUserToOrgMutation();
  const removeMember = useRemoveUserFromOrgMutation();
  const rename = useRenameOrgMutation();
  const deleteOrg = useDeleteOrgMutation();

  if (isLoading) return <LoadingState label="LOADING..." />;
  if (!org) return <ErrorState message="Organization not found" />;

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div className="flex items-center gap-4 text-sm text-muted-foreground mb-4">
        <Link href="/instance/organizations" className="hover:text-foreground flex items-center gap-1"><ArrowLeft className="w-4 h-4" /> Back to Organizations</Link>
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
          <Button variant="outline" onClick={() => setRenameOpen(true)}>
            <Pencil className="w-4 h-4 mr-2" /> Rename
          </Button>
          <Button variant="outline" className="text-destructive hover:bg-destructive hover:text-destructive-foreground"
            onClick={() => setDeleteOpen(true)}>
            <Trash2 className="w-4 h-4 mr-2" /> Delete
          </Button>
        </div>
      </div>

      <Tabs defaultValue="workspaces" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="workspaces" className="gap-2"><TerminalSquare className="w-4 h-4" /> Workspaces</TabsTrigger>
          <TabsTrigger value="keys" className="gap-2"><Key className="w-4 h-4" /> Automation Keys</TabsTrigger>
          <TabsTrigger value="members" className="gap-2"><Users className="w-4 h-4" /> Members</TabsTrigger>
        </TabsList>

        <TabsContent value="workspaces" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Workspaces</h2>
            <Button onClick={() => setWsOpen(true)} size="sm"><Plus className="w-4 h-4 mr-1" /> New Workspace</Button>
          </div>
          <Card>
            <DataTable
              rows={workspacesQuery.data}
              rowKey={ws => ws.id}
              isLoading={workspacesQuery.isLoading}
              isError={workspacesQuery.isError}
              onRetry={() => workspacesQuery.refetch()}
              empty="No workspaces yet."
              columns={[
                {
                  key: 'name',
                  header: 'Name',
                  cellClassName: 'font-medium',
                  cell: ws => (
                    <Link href={`/instance/organizations/${org.id}/workspaces/${ws.slug}`} className="hover:text-primary transition-colors">{ws.name}</Link>
                  ),
                },
                { key: 'slug', header: 'Slug', cell: ws => <Badge variant="mono">{ws.slug}</Badge> },
                { key: 'id', header: 'Technical ID', cellClassName: 'font-mono text-xs text-muted-foreground', cell: ws => ws.id },
                {
                  key: 'created',
                  header: 'Created',
                  headClassName: 'text-right',
                  cellClassName: 'text-right text-muted-foreground text-sm',
                  cell: ws => formatDate(ws.created_at),
                },
              ]}
            />
          </Card>
        </TabsContent>

        <TabsContent value="keys" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Automation Keys</h2>
          </div>
          <ApiKeysTable
            keys={keysQuery.data}
            isLoading={keysQuery.isLoading}
            isError={keysQuery.isError}
            onRetry={() => keysQuery.refetch()}
            emptyText="No management keys for this org."
            extraColumns={[
              {
                key: 'user',
                header: 'User',
                cellClassName: 'text-muted-foreground text-sm',
                 cell: key => {
                   const user = users?.find(candidate => candidate.id === key.user_id);
                   return user ? (
                     <Link href={`/instance/users/${user.id}`} className="hover:text-primary transition-colors">
                       {user.name}
                     </Link>
                   ) : (
                     key.user_id
                   );
                 },
              },
            ]}
            revokeDescription="Requests signed with this management key will stop working immediately. This cannot be undone."
            onRevoke={key => revokeKey.mutate({ keyId: key.id })}
            revokePending={revokeKey.isPending}
          />
        </TabsContent>

        <TabsContent value="members" className="space-y-4 mt-0">
          <MembersPanel
            heading="Organization Members"
            members={members}
            isLoading={membersQuery.isLoading}
            isError={membersQuery.isError}
            onRetry={() => membersQuery.refetch()}
            emptyText="No members yet."
            renderName={member => (
              <Link href={`/instance/users/${member.user_id}`} className="hover:text-primary">{member.name}</Link>
            )}
            add={{
              candidates: (outsiders ?? []).map(user => ({ value: user.id, label: `${user.name} (${user.email})` })),
              dialogTitle: 'Add Member',
              placeholder: 'Select a user',
              onAdd: userId => addMember.mutateAsync({ userId, orgId: org.id }),
              pending: addMember.isPending,
            }}
            remove={{
              title: member => `Remove ${member.name} from the organization?`,
              description: 'They lose access to this organization and all of its workspaces.',
              onRemove: member => removeMember.mutate({ userId: member.user_id, orgId: org.id }),
              pending: removeMember.isPending,
            }}
          />
        </TabsContent>
      </Tabs>

      <FormDialog
        open={wsOpen}
        onOpenChange={setWsOpen}
        title="New Workspace"
        schema={nameSchema}
        defaultValues={{ name: '' }}
        onSubmit={values => createWorkspace.mutateAsync({ data: values })}
        submitLabel="Create"
        pending={createWorkspace.isPending}>
        {form => (
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

      <Modal open={deleteOpen} onOpenChange={setDeleteOpen} title="Delete Organization"
        description="This permanently deletes the organization, its workspaces, keys, members, policies, and usage records.">
        <div className="space-y-4 pt-4">
          <div className="p-4 bg-destructive/10 text-destructive rounded-md flex items-start gap-3 border border-destructive/20">
            <ShieldAlert className="w-5 h-5 flex-shrink-0 mt-0.5" />
            <p className="text-sm font-medium">Deleting <strong>{org.name}</strong> cannot be undone. Usage already recorded remains on the organization’s bill.</p>
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setDeleteOpen(false)}>Cancel</Button>
            <Button variant="destructive" disabled={deleteOrg.isPending}
              onClick={() => deleteOrg.mutate({ orgId: org.id }, { onSuccess: () => setLocation('/instance/organizations') })}>
              Delete Organization
            </Button>
          </div>
        </div>
      </Modal>

      <FormDialog
        open={renameOpen}
        onOpenChange={setRenameOpen}
        title="Rename Organization"
        schema={nameSchema}
        defaultValues={{ name: org.name }}
        onSubmit={values => rename.mutateAsync({ orgId: org.id, data: values })}
        submitLabel="Save"
        pending={rename.isPending}>
        {form => (
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
    </div>
  );
}
