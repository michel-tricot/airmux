import { Card, CardContent, CardHeader, CardTitle, Badge } from '@/components/ui/elements';
import { Building2, Users, Key, Server, Activity } from 'lucide-react';
import { formatRelative } from '@/lib/format';
import { useOrgs } from '@/features/orgs/hooks';
import { useUsers } from '@/features/users/hooks';
import { useInstanceAccessKeys } from '@/features/keys/hooks';
import { useDataPlanes, useInstanceActivity } from '@/features/telemetry/hooks';
import { DataTable } from '@/components/shared/data-table';
import { ErrorState } from '@/components/shared/states';
import { PageShell } from '@/components/shared/page-shell';

export default function Dashboard() {
  const orgsQuery = useOrgs();
  const usersQuery = useUsers();
  const dataPlanesQuery = useDataPlanes();
  const keysQuery = useInstanceAccessKeys();
  const activityQuery = useInstanceActivity({ limit: 25 });
  const usersById = new Map(usersQuery.data?.map((user) => [user.id, user]));
  const actor = (userId: string) => usersById.get(userId)?.email ?? userId;

  const keyLabels = new Map(keysQuery.data?.map((key) => [key.id, key.label] as const) ?? []);
  const describeRecord = (entry: { table_name: string; record_id: string }) => keyLabels.get(entry.record_id) ?? null;

  const statCards = [
    { label: 'Organizations', value: orgsQuery.data?.length, query: orgsQuery, icon: Building2 },
    { label: 'Users', value: usersQuery.data?.length, query: usersQuery, icon: Users },
    { label: 'Access Keys', value: keysQuery.data?.filter((key) => key.status === 'active').length, query: keysQuery, icon: Key },
    {
      label: 'Connected Services',
      value: dataPlanesQuery.data?.filter((dataPlane) => dataPlane.status === 'online').length,
      query: dataPlanesQuery,
      icon: Server,
      active: true,
    },
  ];
  const statsFailed = statCards.some((stat) => stat.query.isError);

  return (
    <PageShell className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">System Overview</h1>
        <p className="text-muted-foreground mt-1 text-sm">Instance-wide totals and the data planes reporting in.</p>
      </div>

      {statsFailed && (
        <ErrorState
          message="Some instance totals could not be loaded. Try again."
          onRetry={() => Promise.all(statCards.map((stat) => stat.query.refetch()))}
        />
      )}

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        {statCards.map((stat) => (
          <Card key={stat.label} className="relative overflow-hidden">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">{stat.label}</CardTitle>
              <stat.icon className={`h-4 w-4 ${stat.active ? 'text-primary' : 'text-muted-foreground'}`} />
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold font-mono">{stat.query.isLoading ? '...' : stat.query.isError ? '-' : (stat.value ?? '-')}</div>
            </CardContent>
            {stat.active && <div className="absolute bottom-0 left-0 right-0 h-1 bg-primary" />}
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Server className="w-5 h-5 text-primary" />
            <CardTitle>Data Planes</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <DataTable
            rows={dataPlanesQuery.data}
            rowKey={(instance) => instance.instance_id}
            isLoading={dataPlanesQuery.isLoading}
            isError={dataPlanesQuery.isError}
            error={dataPlanesQuery.error}
            resource="data planes"
            onRetry={() => dataPlanesQuery.refetch()}
            loadingLabel="Loading connected services..."
            empty="No data plane has reported in yet."
            columns={[
              { key: 'instance', header: 'Instance', cellClassName: 'font-mono text-xs', cell: (i) => i.address ?? i.instance_id },
              { key: 'bundle', header: 'Bundle', cellClassName: 'font-mono text-xs text-muted-foreground', cell: (i) => i.bundle_id ?? 'none' },
              { key: 'version', header: 'Version', cellClassName: 'font-mono text-xs text-muted-foreground', cell: (i) => i.version },
              {
                key: 'status',
                header: 'Status',
                cell: (i) => (
                  <Badge variant={i.status === 'online' ? 'success' : 'outline'} className="font-mono">
                    {i.status.toUpperCase()}
                  </Badge>
                ),
              },
              {
                key: 'last-seen',
                header: 'Last Seen',
                headClassName: 'text-right',
                cellClassName: 'text-right text-muted-foreground text-sm',
                cell: (i) => formatRelative(i.last_seen),
              },
            ]}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-primary" />
            <CardTitle>Activity</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <DataTable
            rows={activityQuery.data}
            rowKey={(entry) => String(entry.id)}
            isLoading={activityQuery.isLoading}
            isError={activityQuery.isError}
            error={activityQuery.error}
            resource="activity"
            onRetry={() => activityQuery.refetch()}
            loadingLabel="Loading activity..."
            empty="Nothing has changed on this instance yet."
            columns={[
              {
                key: 'action',
                header: 'Action',
                headClassName: 'w-[120px]',
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
                key: 'resource',
                header: 'Resource',
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
              { key: 'actor', header: 'Actor', cellClassName: 'text-muted-foreground text-sm', cell: (entry) => actor(entry.user_id) },
              {
                key: 'when',
                header: 'When',
                headClassName: 'text-right',
                cellClassName: 'text-right text-muted-foreground text-sm',
                cell: (entry) => formatRelative(entry.occurred_at),
              },
            ]}
          />
        </CardContent>
      </Card>
    </PageShell>
  );
}
