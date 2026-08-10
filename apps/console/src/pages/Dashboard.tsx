import { useListOrgs, useListUsers, useListDataPlanes, useListAllManagementKeys, useListInstanceActivity } from '@workspace/api-client-react';
import { Card, CardContent, CardHeader, CardTitle, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Badge } from '@/components/ui/elements';
import { Building2, Users, Key, Server, Activity } from 'lucide-react';
import { formatRelative } from '@/lib/format';

export default function Dashboard() {
  const { data: orgs, isLoading: loadingOrgs } = useListOrgs();
  const { data: users } = useListUsers();
  const { data: dataPlanes, isLoading: loadingDataPlanes } = useListDataPlanes();
  const { data: keys } = useListAllManagementKeys();
  const { data: activity, isLoading: loadingActivity } = useListInstanceActivity({ limit: 25 });
  const actor = (userId: string) => users?.find(u => u.id === userId)?.email ?? userId;

  const statCards = [
    { label: 'Organizations', value: orgs?.length ?? '-', icon: Building2 },
    { label: 'Users', value: users?.length ?? '-', icon: Users },
    { label: 'Automation Keys', value: keys?.filter(k => !k.revoked).length ?? '-', icon: Key },
    { label: 'Connected Services', value: dataPlanes?.filter(d => d.status === 'online').length ?? '-', icon: Server, active: true },
  ];

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">System Overview</h1>
        <p className="text-muted-foreground mt-1 text-sm">Instance-wide totals and the data planes reporting in.</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        {statCards.map((stat) => (
          <Card key={stat.label} className="relative overflow-hidden">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {stat.label}
              </CardTitle>
              <stat.icon className={`h-4 w-4 ${stat.active ? 'text-primary' : 'text-muted-foreground'}`} />
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold font-mono">
                {loadingOrgs ? '...' : stat.value}
              </div>
            </CardContent>
            {stat.active && (
              <div className="absolute bottom-0 left-0 right-0 h-1 bg-primary" />
            )}
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
          {loadingDataPlanes ? (
            <div className="py-8 text-center text-muted-foreground font-mono text-sm">Loading connected services...</div>
          ) : dataPlanes && dataPlanes.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Instance</TableHead>
                  <TableHead>Bundle</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Last Seen</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {dataPlanes.map((instance) => (
                  <TableRow key={instance.instance_id}>
                    <TableCell className="font-mono text-xs">{instance.address ?? instance.instance_id}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{instance.bundle_id ?? 'none'}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{instance.version}</TableCell>
                    <TableCell>
                      <Badge variant={instance.status === 'online' ? 'success' : 'outline'} className="font-mono">
                        {instance.status.toUpperCase()}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground text-sm">{formatRelative(instance.last_seen)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="py-8 text-center text-muted-foreground text-sm border-dashed border-2 rounded-md border-border">
              No data plane has reported in yet.
            </div>
          )}
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
          {loadingActivity ? (
            <div className="py-8 text-center text-muted-foreground font-mono text-sm">Loading activity...</div>
          ) : activity && activity.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[120px]">Action</TableHead>
                  <TableHead>Resource</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead className="text-right">When</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activity.map((entry) => (
                  <TableRow key={entry.id}>
                    <TableCell>
                      <Badge variant={entry.action === 'delete' ? 'destructive' : entry.action === 'create' ? 'success' : 'secondary'}
                        className="font-mono">
                        {entry.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-medium">
                      {entry.table_name}
                      <div className="text-xs text-muted-foreground font-mono">{entry.record_id}</div>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">{actor(entry.user_id)}</TableCell>
                    <TableCell className="text-right text-muted-foreground text-sm">{formatRelative(entry.occurred_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="py-8 text-center text-muted-foreground text-sm border-dashed border-2 rounded-md border-border">
              Nothing has changed on this instance yet.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
