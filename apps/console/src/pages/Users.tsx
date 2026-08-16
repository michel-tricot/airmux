import { useState } from 'react';
import * as z from 'zod';
import { Avatar, AvatarFallback, Card, Button, Input, Badge } from '@/components/ui/elements';
import { Users, Search, Bot } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link } from 'wouter';
import { useUsers, useCreateServiceAccountMutation } from '@/features/users/hooks';
import { DataTable } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { PageShell } from '@/components/shared/page-shell';

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

  const filteredUsers = users?.filter(
    (u) => u.name.toLowerCase().includes(search.toLowerCase()) || u.email.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <PageShell>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Global Users</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Every account on the instance, with the orgs it belongs to. Human accounts sign up themselves.
          </p>
        </div>
        <Button onClick={() => setServiceAccountOpen(true)} variant="outline" className="gap-2">
          <Bot className="w-4 h-4" /> Create Service Account
        </Button>
      </div>

      <Card>
        <div className="p-4 border-b border-border flex items-center gap-4">
          <InputGroup className="max-w-sm flex-1 bg-background/50">
            <InputGroupAddon>
              <Search />
            </InputGroupAddon>
            <InputGroupInput
              aria-label="Search users"
              placeholder="Search users..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="font-mono"
            />
          </InputGroup>
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
              cell: (user) => (
                <Link href={`/instance/users/${user.id}`} className="flex items-center gap-2 hover:text-primary transition-colors">
                  <Avatar aria-hidden="true" className="h-6 w-6">
                    <AvatarFallback className="text-xs font-bold">{user.name.charAt(0)}</AvatarFallback>
                  </Avatar>
                  {user.name}
                </Link>
              ),
            },
            { key: 'email', header: 'Email', cellClassName: 'text-muted-foreground text-sm', cell: (user) => user.email },
            {
              key: 'kind',
              header: 'Kind',
              cell: (user) => <Badge variant={user.service_account ? 'secondary' : 'outline'}>{user.service_account ? 'SERVICE' : 'HUMAN'}</Badge>,
            },
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
    </PageShell>
  );
}
