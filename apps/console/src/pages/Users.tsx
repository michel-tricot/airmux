import { useState } from 'react';
import * as z from 'zod';
import { Card, Button, Input, Badge } from '@/components/ui/elements';
import { Users, Plus, Search, Bot } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link } from 'wouter';
import { useUsers, useCreateUserMutation, useCreateServiceAccountMutation } from '@/features/users/hooks';
import { DataTable } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';

const createUserSchema = z.object({
  name: z.string(),
  email: z.string().email('Enter a valid email address'),
});

const createServiceAccountSchema = z.object({
  name: z.string()
    .min(1, 'Name is required')
    .refine(value => /[a-zA-Z0-9]/.test(value), 'Use at least one letter or number'),
});

export default function UsersList() {
  const { data: users, isLoading, isError, refetch } = useUsers();
  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [serviceAccountOpen, setServiceAccountOpen] = useState(false);
  const createUser = useCreateUserMutation();
  const createServiceAccount = useCreateServiceAccountMutation();

  const filteredUsers = users?.filter(u =>
    u.name.toLowerCase().includes(search.toLowerCase()) ||
    u.email.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Global Users</h1>
          <p className="text-muted-foreground mt-1 text-sm">Every account on the instance, with the orgs it belongs to.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setServiceAccountOpen(true)} variant="outline" className="gap-2">
            <Bot className="w-4 h-4" /> Create Service Account
          </Button>
          <Button onClick={() => setCreateOpen(true)} className="gap-2">
            <Plus className="w-4 h-4" /> Add User
          </Button>
        </div>
      </div>

      <Card>
        <div className="p-4 border-b border-border flex items-center gap-4">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search users..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>
        </div>

        <DataTable
          rows={filteredUsers}
          rowKey={user => user.id}
          rowClassName="group"
          isLoading={isLoading}
          isError={isError}
          onRetry={() => refetch()}
          loadingLabel="LOADING..."
          empty="No users found."
          emptyIcon={Users}
          columns={[
            {
              key: 'user',
              header: 'User',
              cellClassName: 'font-medium',
              cell: user => (
                <Link href={`/instance/users/${user.id}`} className="flex items-center gap-2 hover:text-primary transition-colors">
                  <div className="w-6 h-6 rounded-full bg-muted flex items-center justify-center text-xs font-bold text-muted-foreground">
                    {user.name.charAt(0)}
                  </div>
                  {user.name}
                </Link>
              ),
            },
            { key: 'email', header: 'Email', cellClassName: 'text-muted-foreground text-sm', cell: user => user.email },
            {
              key: 'kind',
              header: 'Kind',
              cell: user => (
                <Badge variant={user.service_account ? 'secondary' : 'outline'}>
                  {user.service_account ? 'SERVICE' : 'HUMAN'}
                </Badge>
              ),
            },
            {
              key: 'orgs',
              header: 'Organizations',
              headClassName: 'text-right',
              cellClassName: 'text-right',
              cell: user => <Badge variant="secondary" className="font-mono">{user.orgs.length}</Badge>,
            },
            {
              key: 'created',
              header: 'Created',
              headClassName: 'text-right',
              cellClassName: 'text-right text-muted-foreground text-sm',
              cell: user => formatDate(user.created_at),
            },
          ]}
        />
      </Card>

      <FormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="Add User"
        description="The account starts with no password; the user signs in once one is set."
        schema={createUserSchema}
        defaultValues={{ name: '', email: '' }}
        onSubmit={values => createUser.mutateAsync({ data: values })}
        submitLabel="Add User"
        pendingLabel="Adding..."
        pending={createUser.isPending}>
        {form => (
          <>
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Full Name</FormLabel>
                  <FormControl>
                    <Input placeholder="Jane Doe" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input type="email" placeholder="jane@example.com" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </>
        )}
      </FormDialog>

      <FormDialog
        open={serviceAccountOpen}
        onOpenChange={setServiceAccountOpen}
        title="Create Service Account"
        description="Service accounts cannot sign in. Use them for automation and machine access."
        schema={createServiceAccountSchema}
        defaultValues={{ name: '' }}
        onSubmit={values => createServiceAccount.mutateAsync({ data: values })}
        submitLabel="Create Account"
        pendingLabel="Creating..."
        pending={createServiceAccount.isPending}>
        {form => (
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Name</FormLabel>
                <FormControl>
                  <Input autoFocus placeholder="e.g. Production Worker" {...field} />
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
