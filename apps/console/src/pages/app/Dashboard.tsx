import { useSession } from '@/lib/session';
import { useWorkspaces } from '@/features/workspaces/hooks';
import { useOrgEvents } from '@/features/telemetry/hooks';
import { Card, Badge } from '@/components/ui/elements';
import { TerminalSquare, FolderGit2, Activity } from 'lucide-react';
import { Link } from 'wouter';
import { formatDate, formatRelative } from '@/lib/format';
import { DataTable } from '@/components/shared/data-table';

export default function AppDashboard() {
  const { orgId } = useSession();

  const workspacesQuery = useWorkspaces(orgId!);
  const eventsQuery = useOrgEvents(orgId!, { limit: 10 });

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

        <DataTable
          rows={workspacesQuery.data}
          rowKey={ws => ws.id}
          rowClassName="group"
          isLoading={workspacesQuery.isLoading}
          isError={workspacesQuery.isError}
          onRetry={() => workspacesQuery.refetch()}
          loadingLabel="Loading workspaces..."
          empty="No workspaces in this organization yet."
          emptyIcon={TerminalSquare}
          columns={[
            {
              key: 'workspace',
              header: 'Workspace',
              cellClassName: 'font-medium',
              cell: ws => (
                <Link href={`/org/workspaces/${ws.slug}`} className="flex items-center gap-2 hover:text-primary transition-colors">
                  <FolderGit2 className="w-4 h-4 text-muted-foreground group-hover:text-primary" />
                  {ws.name}
                </Link>
              ),
            },
            { key: 'slug', header: 'Slug', cell: ws => <Badge variant="mono">{ws.slug}</Badge> },
            {
              key: 'created',
              header: 'Created',
              headClassName: 'text-right',
              cellClassName: 'text-right text-muted-foreground text-sm',
              cell: ws => formatDate(ws.created_at),
            },
          ]}
        />
      </Card>

      <Card>
        <div className="p-4 border-b border-border bg-muted/20">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Activity className="w-5 h-5 text-muted-foreground" />
            Recent Usage
          </h2>
        </div>

        <DataTable
          rows={eventsQuery.data}
          rowKey={event => event.event_id}
          isLoading={eventsQuery.isLoading}
          isError={eventsQuery.isError}
          onRetry={() => eventsQuery.refetch()}
          empty="No requests through the gateway yet."
          columns={[
            { key: 'model', header: 'Model', cell: event => <Badge variant="outline" className="font-mono">{event.model_id}</Badge> },
            {
              key: 'status',
              header: 'Status',
              cell: event => (
                <Badge variant={event.status === 'ok' ? 'success' : 'destructive'} className="font-mono">{event.status}</Badge>
              ),
            },
            {
              key: 'tokens',
              header: 'Tokens',
              headClassName: 'text-right',
              cellClassName: 'text-right font-mono text-sm',
              cell: event => event.input_tokens + event.output_tokens,
            },
            {
              key: 'cost',
              header: 'Cost',
              headClassName: 'text-right',
              cellClassName: 'text-right font-mono text-sm',
              cell: event => `$${event.cost_usd.toFixed(4)}`,
            },
            {
              key: 'when',
              header: 'When',
              headClassName: 'text-right',
              cellClassName: 'text-right text-muted-foreground text-sm',
              cell: event => formatRelative(event.occurred_at),
            },
          ]}
        />
      </Card>
    </div>
  );
}
