import { useState } from 'react';
import * as z from 'zod';
import { Card, Button, Dropdown, Modal, Badge, ConfirmButton } from '@/components/ui/elements';
import { ArrowLeft, Building2, Plus, UserMinus, Trash2 } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link, useParams, useLocation } from 'wouter';
import { useOrgs } from '@/features/orgs/hooks';
import {
  useUser,
  useDeleteUserMutation,
  useAddUserToOrgMutation,
  useRemoveUserFromOrgMutation,
} from '@/features/users/hooks';
import { LoadingState, ErrorState } from '@/components/shared/states';
import { DataTable } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';

const addToOrgSchema = z.object({ orgId: z.string().min(1, 'Select an organization') });

export default function UserDetail() {
  const { userId } = useParams();
  const [, setLocation] = useLocation();

  const { data: user, isLoading } = useUser(userId!);
  const orgsQuery = useOrgs();
  const orgs = orgsQuery.data;

  const [addOpen, setAddOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const addMember = useAddUserToOrgMutation();
  const removeMember = useRemoveUserFromOrgMutation();
  const deleteUser = useDeleteUserMutation();

  if (isLoading) return <LoadingState label="LOADING..." />;
  if (!user) return <ErrorState message="User not found" />;

  const memberships = orgs?.filter(o => user.orgs.includes(o.id));
  const available = orgs?.filter(o => !user.orgs.includes(o.id));

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div className="flex items-center gap-4 text-sm text-muted-foreground mb-4">
        <Link href="/instance/users" className="hover:text-foreground flex items-center gap-1"><ArrowLeft className="w-4 h-4" /> Back to Users</Link>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="w-16 h-16 rounded-full bg-primary flex items-center justify-center text-2xl font-bold text-primary-foreground shadow-lg">
            {user.name.charAt(0)}
          </div>
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{user.name}</h1>
            <p className="text-muted-foreground text-sm">{user.email}</p>
            <p className="text-muted-foreground font-mono text-xs mt-1">{user.id}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant={user.service_account ? 'secondary' : 'outline'}>
            {user.service_account ? 'SERVICE ACCOUNT' : 'HUMAN'}
          </Badge>
          <Button variant="outline" className="text-destructive hover:bg-destructive hover:text-destructive-foreground"
            onClick={() => setDeleteOpen(true)}>
            <Trash2 className="w-4 h-4 mr-2" /> Delete
          </Button>
        </div>
      </div>

      <div className="mt-8">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Building2 className="w-5 h-5 text-muted-foreground" />
            Organization Memberships
          </h2>
          <Button onClick={() => setAddOpen(true)} size="sm"><Plus className="w-4 h-4 mr-1" /> Add to Organization</Button>
        </div>
        <Card>
          <DataTable
            rows={memberships}
            rowKey={org => org.id}
            isLoading={orgsQuery.isLoading}
            isError={orgsQuery.isError}
            onRetry={() => orgsQuery.refetch()}
            empty="User does not belong to any organizations."
            columns={[
              {
                key: 'org',
                header: 'Organization',
                cellClassName: 'font-medium',
                cell: org => <Link href={`/instance/organizations/${org.id}`} className="hover:text-primary">{org.name}</Link>,
              },
              { key: 'id', header: 'ID', cellClassName: 'font-mono text-xs text-muted-foreground', cell: org => org.id },
              { key: 'created', header: 'Created', cellClassName: 'text-muted-foreground text-sm', cell: org => formatDate(org.created_at) },
              {
                key: 'actions',
                header: 'Actions',
                headClassName: 'text-right',
                cellClassName: 'text-right',
                cell: org => (
                  <ConfirmButton
                    title={`Remove ${user.name} from ${org.name}?`}
                    description="They lose access to this organization and all of its workspaces."
                    confirmLabel="Remove membership"
                    pending={removeMember.isPending}
                    aria-label="Remove membership"
                    onConfirm={() => removeMember.mutate({ userId: user.id, orgId: org.id })}>
                    <UserMinus className="w-4 h-4" />
                  </ConfirmButton>
                ),
              },
            ]}
          />
        </Card>
      </div>

      <Modal open={deleteOpen} onOpenChange={setDeleteOpen} title="Delete User"
        description="Their sign-in identities, sessions and personal keys go with them.">
        <div className="space-y-4 pt-4">
          <p className="text-sm text-muted-foreground">
            A user who still holds memberships, owns a personal org, or minted inference keys is refused; clear those first.
          </p>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setDeleteOpen(false)}>Cancel</Button>
            <Button variant="destructive" disabled={deleteUser.isPending}
              onClick={() => deleteUser.mutate({ userId: user.id }, { onSuccess: () => setLocation('/instance/users') })}>
              Delete User
            </Button>
          </div>
        </div>
      </Modal>

      <FormDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        title="Add to Organization"
        schema={addToOrgSchema}
        defaultValues={{ orgId: '' }}
        onSubmit={values => addMember.mutateAsync({ userId: user.id, orgId: values.orgId })}
        submitLabel="Add"
        pending={addMember.isPending}>
        {form => (
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
                    options={(available ?? []).map(org => ({ value: org.id, label: org.name }))}
                  />
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
