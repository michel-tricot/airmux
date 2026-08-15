import { useState } from 'react';
import * as z from 'zod';
import { Card, Button, Input, Badge } from '@/components/ui/elements';
import { Building2, Plus, Search } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link } from 'wouter';
import { useOrgs, useCreateOrgMutation } from '@/features/orgs/hooks';
import { DataTable } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { PageShell } from '@/components/shared/page-shell';

const createOrgSchema = z.object({ name: z.string().min(1, 'Name is required') });

export default function Organizations() {
  const orgsQuery = useOrgs();
  const orgs = orgsQuery.data;
  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const createOrg = useCreateOrgMutation();

  const filteredOrgs = orgs?.filter((o) => o.name.toLowerCase().includes(search.toLowerCase()));

  return (
    <PageShell>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Organizations</h1>
          <p className="text-muted-foreground mt-1 text-sm">Organizations group your keys, policies, and usage.</p>
        </div>
        <Button onClick={() => setCreateOpen(true)} className="gap-2">
          <Plus className="w-4 h-4" /> New Organization
        </Button>
      </div>

      <Card>
        <div className="p-4 border-b border-border flex items-center gap-4">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              aria-label="Search organizations"
              placeholder="Search organizations..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>
        </div>

        <DataTable
          rows={filteredOrgs}
          rowKey={(org) => org.id}
          rowClassName="group"
          isLoading={orgsQuery.isLoading}
          isError={orgsQuery.isError}
          error={orgsQuery.error}
          resource="organizations"
          onRetry={() => orgsQuery.refetch()}
          loadingLabel="Loading organizations..."
          empty="No organizations found."
          emptyIcon={Building2}
          columns={[
            {
              key: 'name',
              header: 'Organization Name',
              cellClassName: 'font-medium',
              cell: (org) => (
                <Link href={`/instance/organizations/${org.id}`} className="flex items-center gap-2 hover:text-primary transition-colors">
                  <Building2 className="w-4 h-4 text-muted-foreground group-hover:text-primary" />
                  {org.name}
                </Link>
              ),
            },
            { key: 'id', header: 'ID', cellClassName: 'font-mono text-xs text-muted-foreground', cell: (org) => org.id },
            {
              key: 'kind',
              header: 'Kind',
              cell: (org) => <Badge variant={org.personal_for ? 'secondary' : 'outline'}>{org.personal_for ? 'PERSONAL' : 'SHARED'}</Badge>,
            },
            {
              key: 'created',
              header: 'Created',
              headClassName: 'text-right',
              cellClassName: 'text-right text-muted-foreground text-sm',
              cell: (org) => formatDate(org.created_at),
            },
          ]}
        />
      </Card>

      <FormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="Create Organization"
        description="Set up a new organization."
        schema={createOrgSchema}
        defaultValues={{ name: '' }}
        onSubmit={(values) => createOrg.mutateAsync({ data: values })}
        submitLabel="Create Organization"
        pendingLabel="Creating..."
        pending={createOrg.isPending}
      >
        {(form) => (
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Name</FormLabel>
                <FormControl>
                  <Input placeholder="Acme Corp" {...field} />
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
