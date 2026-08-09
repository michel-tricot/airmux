import { useGetDashboardSummary, useGetRecentActivity } from '@workspace/api-client-react';
import { Card, CardContent, CardHeader, CardTitle, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Badge } from '@/components/ui/elements';
import { Building2, Users, Key, Terminal, Activity } from 'lucide-react';
import { formatRelative } from '@/lib/format';

export default function Dashboard() {
  const { data: summary, isLoading: loadingSummary } = useGetDashboardSummary();
  const { data: activities, isLoading: loadingActivity } = useGetRecentActivity();

  const statCards = [
    { label: 'Organizations', value: summary?.organizationCount ?? '-', icon: Building2 },
    { label: 'Workspaces', value: summary?.workspaceCount ?? '-', icon: Terminal },
    { label: 'Users', value: summary?.userCount ?? '-', icon: Users },
    { label: 'Active Inference Keys', value: summary?.activeInferenceKeyCount ?? '-', icon: Key, active: true },
  ];

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">System Overview</h1>
        <p className="text-muted-foreground mt-1 text-sm">Global gateway metrics and recent platform events.</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        {statCards.map((stat, i) => (
          <Card key={i} className="relative overflow-hidden">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {stat.label}
              </CardTitle>
              <stat.icon className={`h-4 w-4 ${stat.active ? 'text-primary' : 'text-muted-foreground'}`} />
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold font-mono">
                {loadingSummary ? '...' : stat.value}
              </div>
            </CardContent>
            {stat.active && (
              <div className="absolute bottom-0 left-0 right-0 h-1 bg-primary" />
            )}
          </Card>
        ))}
      </div>

      <div className="grid gap-6 md:grid-cols-1">
        <Card className="col-span-1">
          <CardHeader>
            <div className="flex items-center gap-2">
              <Activity className="w-5 h-5 text-primary" />
              <CardTitle>Activity Feed</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            {loadingActivity ? (
              <div className="py-8 text-center text-muted-foreground font-mono text-sm">LOADING EVENTS...</div>
            ) : Array.isArray(activities) && activities.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[180px]">Event Type</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead className="text-right">Time</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {activities.map((event) => {
                    const isAlert = event.type.includes('revoked') || event.type.includes('deleted');
                    const isCreate = event.type.includes('created') || event.type.includes('added');
                    return (
                      <TableRow key={event.id}>
                        <TableCell>
                          <Badge variant={isAlert ? 'destructive' : isCreate ? 'success' : 'secondary'} className="font-mono">
                            {event.type}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-medium">{event.message}</TableCell>
                        <TableCell className="text-right text-muted-foreground text-sm">
                          {formatRelative(event.createdAt)}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            ) : (
              <div className="py-8 text-center text-muted-foreground text-sm border-dashed border-2 rounded-md border-border">
                No recent activity recorded.
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
