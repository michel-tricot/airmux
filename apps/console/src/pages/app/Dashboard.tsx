import { useSession } from '@/lib/session';
import { orgScope } from '@/lib/api';
import {
  useListWorkspaces,
  useListEvents,
  getListWorkspacesQueryKey,
  getListEventsQueryKey,
} from '@workspace/api-client-react';
import { Card, Badge, Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from '@/components/ui/elements';
import { TerminalSquare, FolderGit2, Activity } from 'lucide-react';
import { Link } from 'wouter';
import { formatDate, formatRelative } from '@/lib/format';

export default function AppDashboard() {
  const { orgId } = useSession();
  const scope = orgScope(orgId!);

  const { data: workspaces, isLoading } = useListWorkspaces({
    query: { queryKey: [...getListWorkspacesQueryKey(), orgId] },
    request: scope,
  });
  const { data: events } = useListEvents({ limit: 10 }, {
    query: { queryKey: [...getListEventsQueryKey({ limit: 10 }), orgId] },
    request: scope,
  });

  return (
    <div className="flex-1 p-8 max-w-5xl mx-auto w-full space-y-6 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Organization Overview</h1>
        <p className="text-muted-foreground mt-1 text-sm">Select a workspace to manage its keys and access.</p>
      </div>

      <Card>
        <div className="p-4 border-b border-border bg-muted/20">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <TerminalSquare className="w-5 h-5 text-muted-foreground" />
            Workspaces
          </h2>
        </div>

        {isLoading ? (
          <div className="py-12 text-center text-muted-foreground font-mono text-sm">LOADING WORKSPACES...</div>
        ) : workspaces && workspaces.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Workspace</TableHead>
                <TableHead>Slug</TableHead>
                <TableHead>ID</TableHead>
                <TableHead className="text-right">Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {workspaces.map(ws => (
                <TableRow key={ws.id} className="group">
                  <TableCell className="font-medium">
                    <Link href={`/org/workspaces/${ws.id}`} className="flex items-center gap-2 hover:text-primary transition-colors">
                      <FolderGit2 className="w-4 h-4 text-muted-foreground group-hover:text-primary" />
                      {ws.name}
                    </Link>
                  </TableCell>
                  <TableCell><Badge variant="mono">{ws.slug}</Badge></TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{ws.id}</TableCell>
                  <TableCell className="text-right text-muted-foreground text-sm">{formatDate(ws.created_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="text-center p-12 text-muted-foreground">
            <TerminalSquare className="w-12 h-12 mx-auto mb-4 opacity-20" />
            <p>No workspaces in this organization yet.</p>
          </div>
        )}
      </Card>

      <Card>
        <div className="p-4 border-b border-border bg-muted/20">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Activity className="w-5 h-5 text-muted-foreground" />
            Recent Usage
          </h2>
        </div>

        {events && events.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Model</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Tokens</TableHead>
                <TableHead className="text-right">Cost</TableHead>
                <TableHead className="text-right">When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map(event => (
                <TableRow key={event.event_id}>
                  <TableCell className="font-mono text-xs">{event.model_id}</TableCell>
                  <TableCell>
                    <Badge variant={event.status === 'ok' ? 'success' : 'destructive'} className="font-mono">{event.status}</Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">{event.input_tokens + event.output_tokens}</TableCell>
                  <TableCell className="text-right font-mono text-sm">${event.cost_usd.toFixed(4)}</TableCell>
                  <TableCell className="text-right text-muted-foreground text-sm">{formatRelative(event.occurred_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="p-8 text-center text-muted-foreground text-sm">No requests through the gateway yet.</div>
        )}
      </Card>
    </div>
  );
}
