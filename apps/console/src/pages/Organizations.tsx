import { useState } from 'react';
import { Card, Button, Badge } from '@/components/ui/elements';
import { Building2, Plus } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { useOrgs, useCreateOrgMutation } from '@/features/orgs/hooks';
import { DataTable } from '@/components/shared/data-table';
import { TableLink } from '@/components/shared/table-link';
import { CreateOrganizationDialog } from '@/components/shared/create-organization-dialog';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { SearchField } from '@/components/shared/search-field';
import { useAuthorization } from '@/features/permissions/hooks';
import { orgAccess } from '@/features/orgs/policy';

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
          hasNextPage={orgsQuery.hasNextPage}
          isFetchingNextPage={orgsQuery.isFetchingNextPage}
          onLoadMore={() => void orgsQuery.fetchNextPage()}
          columns={[
            {
              key: 'name',
              header: 'Organization Name',
              cellClassName: 'font-medium',
              cell: (org) => (
                <TableLink href={`/instance/organizations/${org.id}`} className="flex items-center gap-2">
                  <Building2 className="w-4 h-4 text-muted-foreground group-hover:text-primary" />
                  {org.name}
                </TableLink>
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
        <CreateOrganizationDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          onSubmit={(values) => createOrg.mutateAsync({ data: values })}
          pending={createOrg.isPending}
        />
      )}
    </PageShell>
  );
}
