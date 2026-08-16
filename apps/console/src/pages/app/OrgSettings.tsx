import { useState } from 'react';
import { useRequiredOrgId } from '@/lib/session';
import { useAccessKeys, useCreateAccessKeyMutation, useRevokeAccessKeyMutation } from '@/features/keys/hooks';
import { useOrgMembers } from '@/features/members/hooks';
import { useBundles, useCompileBundleMutation, useOrgActivity } from '@/features/telemetry/hooks';
import { Avatar, AvatarFallback, Card, Button, Badge, Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/elements';
import { Plus, Key, Settings, Package, RefreshCw, Users, Activity } from 'lucide-react';
import { formatDate, formatRelative } from '@/lib/format';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { PageShell } from '@/components/shared/page-shell';
import { DataTable } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { ApiKeysTable } from '@/components/shared/api-keys-table';
import { AccessKeyFormFields, accessKeyFormSchema, parsePermissions } from '@/components/shared/access-key-form';

export default function AppOrgSettings() {
  const orgId = useRequiredOrgId();

  const keysQuery = useAccessKeys({ org_id: orgId });
  const bundlesQuery = useBundles(orgId);
  const membersQuery = useOrgMembers(orgId);
  const activityQuery = useOrgActivity(orgId, { limit: 50 });
  const members = membersQuery.data;

  const [keyOpen, setKeyOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);

  const keyLabels = new Map(keysQuery.data?.map((key) => [key.id, key.label] as const) ?? []);
  const describeRecord = (entry: { record_id: string }) => keyLabels.get(entry.record_id) ?? null;

  const mintKey = useCreateAccessKeyMutation();
  const revokeKey = useRevokeAccessKeyMutation();
  const compile = useCompileBundleMutation(orgId);

  return (
    <PageShell className="max-w-5xl">
      <div className="flex items-center gap-4 mb-8">
        <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
          <Settings className="w-6 h-6 text-primary" />
        </div>
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Organization Settings</h1>
          <p className="text-muted-foreground mt-1 text-sm">Manage automation credentials and published organization policies.</p>
        </div>
      </div>

      <Tabs defaultValue="keys" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="keys" className="gap-2">
            <Key className="w-4 h-4" /> Automation Keys
          </TabsTrigger>
          <TabsTrigger value="bundles" className="gap-2">
            <Package className="w-4 h-4" /> Policies
          </TabsTrigger>
          <TabsTrigger value="members" className="gap-2">
            <Users className="w-4 h-4" /> Members
          </TabsTrigger>
          <TabsTrigger value="activity" className="gap-2">
            <Activity className="w-4 h-4" /> Activity
          </TabsTrigger>
        </TabsList>

        <TabsContent value="keys" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Automation Keys</h2>
            <Button onClick={() => setKeyOpen(true)} size="sm" className="shadow-sm">
              <Plus className="w-4 h-4 mr-1" /> Generate Key
            </Button>
          </div>
          <ApiKeysTable
            keys={keysQuery.data}
            isLoading={keysQuery.isLoading}
            isError={keysQuery.isError}
            error={keysQuery.error}
            onRetry={() => keysQuery.refetch()}
            emptyText="No access keys generated."
            extraColumns={[
              {
                key: 'permissions',
                header: 'Permissions',
                cellClassName: 'font-mono text-xs text-muted-foreground',
                cell: (key) => key.permissions.join(', '),
              },
              { key: 'boundary', header: 'Boundary', cellClassName: 'text-muted-foreground text-sm', cell: (key) => key.boundary },
            ]}
            revokeDescription="This key and every key delegated from it will stop working immediately."
            onRevoke={(key) => revokeKey.mutateAsync({ keyId: key.id })}
            revokePending={revokeKey.isPending}
          />
        </TabsContent>

        <TabsContent value="bundles" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Access Policies</h2>
            <Button onClick={() => compile.mutate()} size="sm" disabled={compile.isPending}>
              <RefreshCw className="w-4 h-4 mr-1" /> {compile.isPending ? 'Publishing...' : 'Publish policy'}
            </Button>
          </div>
          <Card>
            <DataTable
              rows={bundlesQuery.data ? [...bundlesQuery.data].reverse() : undefined}
              rowKey={(bundle) => bundle.id}
              isLoading={bundlesQuery.isLoading}
              isError={bundlesQuery.isError}
              error={bundlesQuery.error}
              resource="policies"
              onRetry={() => bundlesQuery.refetch()}
              empty="No policies have been published yet."
              columns={[
                { key: 'version', header: 'Version', cellClassName: 'font-mono font-medium', cell: (bundle) => `v${bundle.version}` },
                { key: 'id', header: 'Policy ID', cellClassName: 'font-mono text-xs text-muted-foreground', cell: (bundle) => bundle.id },
                {
                  key: 'published',
                  header: 'Published',
                  cellClassName: 'text-muted-foreground text-sm',
                  cell: (bundle) => formatDate(bundle.issued_at),
                },
                {
                  key: 'expires',
                  header: 'Expires',
                  headClassName: 'text-right',
                  cellClassName: 'text-right text-muted-foreground text-sm',
                  cell: (bundle) => formatDate(bundle.expires_at),
                },
              ]}
            />
          </Card>
        </TabsContent>

        <TabsContent value="members" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Organization Members</h2>
          </div>
          <Card>
            <DataTable
              rows={members}
              rowKey={(member) => member.user_id}
              isLoading={membersQuery.isLoading}
              isError={membersQuery.isError}
              error={membersQuery.error}
              resource="members"
              onRetry={() => membersQuery.refetch()}
              empty="No members found."
              columns={[
                {
                  key: 'name',
                  header: 'Name',
                  cellClassName: 'font-medium',
                  cell: (member) => (
                    <span className="flex items-center gap-2">
                      <Avatar aria-hidden="true" className="h-6 w-6">
                        <AvatarFallback className="bg-primary/10 text-xs font-bold text-primary">{member.name.charAt(0)}</AvatarFallback>
                      </Avatar>
                      {member.name}
                    </span>
                  ),
                },
                { key: 'email', header: 'Email', cellClassName: 'text-muted-foreground', cell: (member) => member.email },
                { key: 'role', header: 'Role', cellClassName: 'text-muted-foreground', cell: (member) => member.role },
                {
                  key: 'kind',
                  header: 'Account type',
                  headClassName: 'text-right',
                  cellClassName: 'text-right',
                  cell: (member) => (
                    <Badge variant={member.service_account ? 'secondary' : 'outline'}>{member.service_account ? 'Service account' : 'User'}</Badge>
                  ),
                },
              ]}
            />
          </Card>
        </TabsContent>

        <TabsContent value="activity" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Recent activity</h2>
          </div>
          <Card>
            <DataTable
              rows={activityQuery.data}
              rowKey={(entry) => String(entry.id)}
              isLoading={activityQuery.isLoading}
              isError={activityQuery.isError}
              error={activityQuery.error}
              resource="activity"
              onRetry={() => activityQuery.refetch()}
              empty="Nothing has changed in this org yet."
              columns={[
                {
                  key: 'change',
                  header: 'Change',
                  cell: (entry) => (
                    <Badge
                      variant={entry.action === 'delete' ? 'destructive' : entry.action === 'create' ? 'success' : 'secondary'}
                      className="font-mono"
                    >
                      {entry.action}
                    </Badge>
                  ),
                },
                {
                  key: 'item',
                  header: 'Item',
                  cellClassName: 'font-medium',
                  cell: (entry) => {
                    const label = describeRecord(entry);
                    return (
                      <>
                        {entry.table_name}
                        {label && <span className="ml-2 text-muted-foreground">“{label}”</span>}
                        <div className="text-xs text-muted-foreground font-mono">{entry.record_id}</div>
                      </>
                    );
                  },
                },
                {
                  key: 'actor',
                  header: 'Changed by',
                  cellClassName: 'font-mono text-xs text-muted-foreground',
                  cell: (entry) => members?.find((m) => m.user_id === entry.user_id)?.email ?? entry.user_id,
                },
                {
                  key: 'when',
                  header: 'When',
                  headClassName: 'text-right',
                  cellClassName: 'text-right text-muted-foreground text-sm',
                  cell: (entry) => formatRelative(entry.occurred_at),
                },
              ]}
            />
          </Card>
        </TabsContent>
      </Tabs>

      <FormDialog
        open={keyOpen}
        onOpenChange={setKeyOpen}
        title="Create an organization access key"
        description="The key is bound to this organization and carries only the permissions you name."
        schema={accessKeyFormSchema}
        defaultValues={{ label: '', permissions: '' }}
        onSubmit={async (values) => {
          const minted = await mintKey.mutateAsync({
            data: { label: values.label, org_id: orgId, permissions: parsePermissions(values.permissions) },
          });
          setToken(minted.token);
        }}
        submitLabel="Generate"
        pending={mintKey.isPending}
      >
        {(form) => <AccessKeyFormFields form={form} />}
      </FormDialog>

      <KeyRevealDialog open={!!token} onOpenChange={(v) => !v && setToken(null)} token={token} />
    </PageShell>
  );
}
