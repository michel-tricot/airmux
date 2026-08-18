import { useState } from 'react';
import * as z from 'zod';
import { Card, Button, Input, Badge } from '@/components/ui/elements';
import { Building2, Plus } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link } from 'wouter';
import { useOrgs, useCreateOrgMutation } from '@/features/orgs/hooks';
import { DataTable } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { SearchField } from '@/components/shared/search-field';
import { useAuthorization } from '@/features/permissions/hooks';
import { orgAccess } from '@/features/orgs/policy';

const createOrgSchema = z.object({ name: z.string().min(1, 'Name is required') });

export default function Organizations() {
  const orgsQuery = useOrgs();
  const orgs = orgsQuery.data;
  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const createOrg = useCreateOrgMutation();
  const authorization = useAuthorization('instance');
  const canCreate = authorization.can(orgAccess.create);

  const filteredOrgs = orgs?.filter((o) => o.name.toLowerCase().includes(search.toLowerCase()));

  return (
    <PageShell>
      <PageHeader
        title="Organizations"
        description="Organizations group your keys, policies, and usage."
        actions={
          canCreate && (
            <Button onClick={() => setCreateOpen(true)} className="gap-2">
              <Plus className="w-4 h-4" /> New Organization
            </Button>
          )
        }
      />

      <Card>
        <div className="p-4 border-b border-border flex items-center gap-4">
          <SearchField value={search} onValueChange={setSearch} label="Search organizations" placeholder="Search organizations..." />
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

      {canCreate && (
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
      )}
    </PageShell>
  );
}
