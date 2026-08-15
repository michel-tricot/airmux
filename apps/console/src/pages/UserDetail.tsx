import { useState } from 'react';
import * as z from 'zod';
import { Avatar, AvatarFallback, Card, Button, Dropdown, Badge, ConfirmButton } from '@/components/ui/elements';
import { ArrowLeft, Building2, KeyRound, Plus, UserMinus, Trash2 } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link, useLocation } from 'wouter';
import { useOrgs } from '@/features/orgs/hooks';
import { useAllManagementKeys, useInstanceKeys } from '@/features/keys/hooks';
import { useUser, useDeleteUserMutation, useAddUserToOrgMutation, useRemoveUserFromOrgMutation } from '@/features/users/hooks';
import { LoadingState, ErrorState } from '@/components/shared/states';
import { DataTable } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { useRequiredParam } from '@/lib/route';
import { PageShell } from '@/components/shared/page-shell';

const addToOrgSchema = z.object({ orgId: z.string().min(1, 'Select an organization') });

export default function UserDetail() {
  const userId = useRequiredParam('userId');
  const [, setLocation] = useLocation();

  const userQuery = useUser(userId);
  const user = userQuery.data;
  const orgsQuery = useOrgs();
  const orgs = orgsQuery.data;
  const instanceKeysQuery = useInstanceKeys();
  const managementKeysQuery = useAllManagementKeys();

  const [addOpen, setAddOpen] = useState(false);

  const addMember = useAddUserToOrgMutation();
  const removeMember = useRemoveUserFromOrgMutation();
  const deleteUser = useDeleteUserMutation();

  if (userQuery.isLoading) return <LoadingState label="Loading user..." />;
  if (userQuery.isError) return <ErrorState error={userQuery.error} resource="user" onRetry={() => userQuery.refetch()} />;
  if (!user) return <ErrorState message="User not found" />;

  const memberships = orgs?.filter((o) => user.orgs.includes(o.id));
  const available = orgs?.filter((o) => !user.orgs.includes(o.id));
  const instanceKeys = instanceKeysQuery.data?.filter((key) => key.user_id === user.id);
  const managementKeys = managementKeysQuery.data?.filter((key) => key.user_id === user.id);

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
          <Badge variant={user.service_account ? 'secondary' : 'outline'}>{user.service_account ? 'SERVICE ACCOUNT' : 'HUMAN'}</Badge>
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
        </div>
      </div>

      <div className="mt-8">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Building2 className="w-5 h-5 text-muted-foreground" />
            Organization Memberships
          </h2>
          <Button onClick={() => setAddOpen(true)} size="sm" disabled={orgsQuery.isLoading || orgsQuery.isError || available?.length === 0}>
            <Plus className="w-4 h-4 mr-1" /> Add to Organization
          </Button>
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
              {
                key: 'actions',
                header: 'Actions',
                headClassName: 'text-right',
                cellClassName: 'text-right',
                cell: (org) => (
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
            ]}
          />
        </Card>
      </div>

      <div className="mt-8">
        <h2 className="text-lg font-semibold flex items-center gap-2 mb-4">
          <KeyRound className="w-5 h-5 text-muted-foreground" />
          Keys owned by this user
        </h2>

        <div className="space-y-6">
          <Card>
            <DataTable
              rows={instanceKeys}
              rowKey={(key) => key.id}
              isLoading={instanceKeysQuery.isLoading}
              isError={instanceKeysQuery.isError}
              error={instanceKeysQuery.error}
              resource="instance keys"
              onRetry={() => instanceKeysQuery.refetch()}
              empty="This user does not own any instance keys."
              columns={[
                { key: 'type', header: 'Type', cell: () => <Badge variant="secondary">INSTANCE</Badge> },
                { key: 'label', header: 'Label', cellClassName: 'font-medium', cell: (key) => key.label },
                { key: 'key', header: 'Key', cellClassName: 'font-mono text-xs text-muted-foreground', cell: (key) => <>{key.prefix}…</> },
                {
                  key: 'status',
                  header: 'Status',
                  cell: (key) => <Badge variant={key.revoked ? 'outline' : 'success'}>{key.revoked ? 'REVOKED' : 'ACTIVE'}</Badge>,
                },
                { key: 'created', header: 'Created', cellClassName: 'text-muted-foreground text-sm', cell: (key) => formatDate(key.created_at) },
              ]}
            />
          </Card>

          <Card>
            <DataTable
              rows={managementKeys}
              rowKey={(key) => key.id}
              isLoading={managementKeysQuery.isLoading}
              isError={managementKeysQuery.isError}
              error={managementKeysQuery.error}
              resource="management keys"
              onRetry={() => managementKeysQuery.refetch()}
              empty="This user does not own any management keys."
              columns={[
                { key: 'type', header: 'Type', cell: () => <Badge variant="secondary">MANAGEMENT</Badge> },
                { key: 'label', header: 'Label', cellClassName: 'font-medium', cell: (key) => key.label },
                { key: 'key', header: 'Key', cellClassName: 'font-mono text-xs text-muted-foreground', cell: (key) => <>{key.prefix}…</> },
                {
                  key: 'status',
                  header: 'Status',
                  cell: (key) => <Badge variant={key.revoked ? 'outline' : 'success'}>{key.revoked ? 'REVOKED' : 'ACTIVE'}</Badge>,
                },
                { key: 'created', header: 'Created', cellClassName: 'text-muted-foreground text-sm', cell: (key) => formatDate(key.created_at) },
              ]}
            />
          </Card>
        </div>
      </div>

      <FormDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        title="Add to Organization"
        schema={addToOrgSchema}
        defaultValues={{ orgId: '' }}
        onSubmit={(values) => addMember.mutateAsync({ userId: user.id, orgId: values.orgId })}
        submitLabel="Add"
        pending={addMember.isPending}
      >
        {(form) => (
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
        )}
      </FormDialog>
    </PageShell>
  );
}
