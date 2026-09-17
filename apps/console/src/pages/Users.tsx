import { useState } from 'react';
import * as z from 'zod';
import { Card, Button, Input, Badge } from '@/components/ui/elements';
import { Users, Bot } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { useUsers, useCreateServiceAccountMutation } from '@/features/users/hooks';
import { DataTable } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { SearchField } from '@/components/shared/search-field';
import { useAuthorization } from '@/features/permissions/hooks';
import { userAccess } from '@/features/users/policy';
import { AccountIdentity, AccountKindBadge } from '@/components/shared/account-display';

const createServiceAccountSchema = z.object({
  name: z
    .string()
    .min(1, 'Name is required')
    .max(200, 'Use 200 characters or fewer')
    .refine((value) => /[a-zA-Z0-9]/.test(value), 'Use at least one letter or number'),
});

export default function UsersList() {
  const usersQuery = useUsers();
  const users = usersQuery.data;
  const [search, setSearch] = useState('');
  const [serviceAccountOpen, setServiceAccountOpen] = useState(false);
  const createServiceAccount = useCreateServiceAccountMutation();
  const authorization = useAuthorization('instance');
  const canCreateServiceAccount = authorization.can(userAccess.createServiceAccount);

  const filteredUsers = users?.filter(
    (u) => u.name.toLowerCase().includes(search.toLowerCase()) || u.email.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <PageShell>
      <PageHeader
        title="Global Users"
        description="Every account on the instance, with the orgs it belongs to. Human accounts sign up themselves."
        actions={
          canCreateServiceAccount && (
            <Button onClick={() => setServiceAccountOpen(true)} variant="outline" className="gap-2">
              <Bot className="w-4 h-4" /> Create Service Account
            </Button>
          )
        }
      />

      <Card>
        <div className="p-4 border-b border-border flex items-center gap-4">
          <SearchField value={search} onValueChange={setSearch} label="Search users" placeholder="Search users..." />
        </div>

        <DataTable
          rows={filteredUsers}
          rowKey={(user) => user.id}
          rowClassName="group"
          isLoading={usersQuery.isLoading}
          isError={usersQuery.isError}
          error={usersQuery.error}
          resource="users"
          onRetry={() => usersQuery.refetch()}
          loadingLabel="Loading users..."
          empty="No users found."
          emptyIcon={Users}
          columns={[
            {
              key: 'user',
              header: 'User',
              cellClassName: 'font-medium',
              cell: (user) => <AccountIdentity name={user.name} href={`/instance/users/${user.id}`} />,
            },
            { key: 'email', header: 'Email', cellClassName: 'text-muted-foreground text-sm', cell: (user) => user.email },
            {
              key: 'kind',
              header: 'Kind',
              cell: (user) => <AccountKindBadge serviceAccount={user.service_account} />,
            },
            { key: 'role', header: 'Instance role', cell: (user) => user.instance_role ?? 'None' },
            {
              key: 'orgs',
              header: 'Organizations',
              headClassName: 'text-right',
              cellClassName: 'text-right',
              cell: (user) => (
                <Badge variant="secondary" className="font-mono">
                  {user.orgs.length}
                </Badge>
              ),
            },
            {
              key: 'created',
              header: 'Created',
              headClassName: 'text-right',
              cellClassName: 'text-right text-muted-foreground text-sm',
              cell: (user) => formatDate(user.created_at),
            },
          ]}
        />
      </Card>

      {canCreateServiceAccount && (
        <FormDialog
          open={serviceAccountOpen}
          onOpenChange={setServiceAccountOpen}
          title="Create Service Account"
          description="Service accounts cannot sign in. Use them for automation and machine access."
          schema={createServiceAccountSchema}
          defaultValues={{ name: '' }}
          onSubmit={(values) => createServiceAccount.mutateAsync({ data: values })}
          submitLabel="Create Account"
          pendingLabel="Creating..."
          pending={createServiceAccount.isPending}
        >
          {(form) => (
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input placeholder="e.g. Production Worker" {...field} />
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
