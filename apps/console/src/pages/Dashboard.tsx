import { Card, CardContent, CardHeader, CardTitle, Badge } from '@/components/ui/elements';
import { Building2, Users, Key, Server, Activity } from 'lucide-react';
import { formatRelative } from '@/lib/format';
import { useOrgs } from '@/features/orgs/hooks';
import { useUsers } from '@/features/users/hooks';
import { useInstanceAccessKeys } from '@/features/keys/hooks';
import { useDataPlanes, useInstanceActivity } from '@/features/telemetry/hooks';
import { DataTable } from '@/components/shared/data-table';
import { ActivityTable } from '@/components/shared/activity-table';
import { ErrorState } from '@/components/shared/states';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { useAuthorization } from '@/features/permissions/hooks';
import { accessKeyAccess } from '@/features/keys/policy';
import { orgAccess } from '@/features/orgs/policy';
import { telemetryAccess } from '@/features/telemetry/policy';
import { userAccess } from '@/features/users/policy';

export default function Dashboard() {
  const authorization = useAuthorization('instance');
  const canListOrgs = authorization.can(orgAccess.list);
  const canListUsers = authorization.can(userAccess.list);
  const canReadKeys = authorization.can(accessKeyAccess.instance.read);
  const canReadDataPlanes = authorization.can(telemetryAccess.dataPlanes);
  const canReadActivity = authorization.can(telemetryAccess.instanceActivity);
  const orgsQuery = useOrgs({ enabled: canListOrgs });
  const usersQuery = useUsers({ enabled: canListUsers });
  const dataPlanesQuery = useDataPlanes({ enabled: canReadDataPlanes });
  const keysQuery = useInstanceAccessKeys(undefined, { enabled: canReadKeys });
  const activityQuery = useInstanceActivity({ limit: 25 }, { enabled: canReadActivity });
  const usersById = new Map(usersQuery.data?.map((user) => [user.id, user]));
  const actor = (userId: string) => usersById.get(userId)?.email ?? userId;

  const keyLabels = new Map(keysQuery.data?.map((key) => [key.id, key.label] as const) ?? []);
  const describeRecord = (entry: { table_name: string; record_id: string }) => keyLabels.get(entry.record_id) ?? null;

  const statCards = [
    ...(canListOrgs ? [{ label: 'Organizations', value: orgsQuery.data?.length, query: orgsQuery, icon: Building2 }] : []),
    ...(canListUsers ? [{ label: 'Users', value: usersQuery.data?.length, query: usersQuery, icon: Users }] : []),
    ...(canReadKeys
      ? [{ label: 'Management Keys', value: keysQuery.data?.filter((key) => key.status === 'active').length, query: keysQuery, icon: Key }]
      : []),
    ...(canReadDataPlanes
      ? [
          {
            label: 'Connected Services',
            value: dataPlanesQuery.data?.filter((dataPlane) => dataPlane.status === 'online').length,
            query: dataPlanesQuery,
            icon: Server,
            active: true,
          },
        ]
      : []),
  ];
  const statsFailed = statCards.some((stat) => stat.query.isError);

  return (
    <PageShell className="space-y-8">
      <PageHeader title="System Overview" description="Instance-wide totals and the data planes reporting in." />

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

      {canReadDataPlanes && (
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
      )}

      {canReadActivity && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Activity className="w-5 h-5 text-primary" />
              <CardTitle>Activity</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <ActivityTable
              entries={activityQuery.data}
              isLoading={activityQuery.isLoading}
              isError={activityQuery.isError}
              error={activityQuery.error}
              onRetry={() => activityQuery.refetch()}
              emptyText="Nothing has changed on this instance yet."
              recordLabel={describeRecord}
              renderActor={(entry) => actor(entry.user_id)}
            />
          </CardContent>
        </Card>
      )}
    </PageShell>
  );
}
