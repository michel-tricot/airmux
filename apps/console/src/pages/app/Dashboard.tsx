import { useRequiredOrgId } from '@/lib/session';
import { useWorkspaces } from '@/features/workspaces/hooks';
import { useOrgEvents } from '@/features/telemetry/hooks';
import { Card, Badge } from '@/components/ui/elements';
import { TerminalSquare, FolderGit2, Activity } from 'lucide-react';
import { Link } from 'wouter';
import { formatDate } from '@/lib/format';
import { DataTable } from '@/components/shared/data-table';
import { TokenUsageSource } from '@/components/shared/token-usage-source';
import { PageHeader, PageShell, SectionHeader } from '@/components/shared/page-shell';
import { useAuthorization } from '@/features/permissions/hooks';
import { telemetryAccess } from '@/features/telemetry/policy';
import { workspaceAccess } from '@/features/workspaces/policy';
import { formatUsd, parseUsdAmount } from '@/lib/money';

export default function AppDashboard() {
  const orgId = useRequiredOrgId();
  const authorization = useAuthorization('org');
  const canReadWorkspaces = authorization.can(workspaceAccess.list);
  const canReadUsage = authorization.can(telemetryAccess.orgUsage);

  const workspacesQuery = useWorkspaces(orgId, { enabled: canReadWorkspaces });
  const eventsQuery = useOrgEvents(orgId, { limit: 10 }, { enabled: canReadUsage });

  return (
    <PageShell className="max-w-5xl">
      <PageHeader title="Organization Overview" description="Select a workspace to manage its keys and access." />

      {canReadWorkspaces && (
        <Card>
          <SectionHeader title="Workspaces" icon={TerminalSquare} className="border-b border-border bg-muted/20 p-4" />

          <DataTable
            rows={workspacesQuery.data}
            rowKey={(ws) => ws.id}
            rowClassName="group"
            isLoading={workspacesQuery.isLoading}
            isError={workspacesQuery.isError}
            error={workspacesQuery.error}
            resource="workspaces"
            onRetry={() => workspacesQuery.refetch()}
            loadingLabel="Loading workspaces..."
            empty="No workspaces in this organization yet."
            emptyIcon={TerminalSquare}
            columns={[
              {
                key: 'workspace',
                header: 'Workspace',
                cellClassName: 'font-medium',
                cell: (ws) => (
                  <Link href={`/org/workspaces/${ws.slug}`} className="flex items-center gap-2 hover:text-primary transition-colors">
                    <FolderGit2 className="w-4 h-4 text-muted-foreground group-hover:text-primary" />
                    {ws.name}
                  </Link>
                ),
              },
              { key: 'slug', header: 'Slug', cell: (ws) => <Badge variant="mono">{ws.slug}</Badge> },
              {
                key: 'created',
                header: 'Created',
                headClassName: 'text-right',
                cellClassName: 'text-right text-muted-foreground text-sm',
                cell: (ws) => formatDate(ws.created_at),
              },
            ]}
          />
        </Card>
      )}

      {canReadUsage && (
        <Card>
          <SectionHeader title="Recent Usage" icon={Activity} className="border-b border-border bg-muted/20 p-4" />

          <DataTable
            rows={eventsQuery.data}
            rowKey={(event) => event.event_id}
            isLoading={eventsQuery.isLoading}
            isError={eventsQuery.isError}
            error={eventsQuery.error}
            resource="usage"
            onRetry={() => eventsQuery.refetch()}
            empty="No requests through the gateway yet."
            columns={[
              {
                key: 'model',
                header: 'Model',
                cell: (event) => (
                  <Badge variant="outline" className="font-mono">
                    {event.model_id}
                  </Badge>
                ),
              },
              {
                key: 'status',
                header: 'Status',
                cell: (event) => (
                  <Badge variant={event.status === 'ok' ? 'success' : 'destructive'} className="font-mono">
                    {event.status}
                  </Badge>
                ),
              },
              {
                key: 'tokens',
                header: 'Tokens',
                headClassName: 'text-right',
                cellClassName: 'text-right font-mono text-sm',
                cell: (event) => event.input_tokens + event.output_tokens,
              },
              {
                key: 'token_source',
                header: 'Token source',
                cell: (event) => <TokenUsageSource source={event.token_usage_source} />,
              },
              {
                key: 'cost',
                header: 'Est. cost',
                headClassName: 'text-right',
                cellClassName: 'text-right font-mono text-sm',
                cell: (event) => formatUsd(parseUsdAmount(event.cost_usd)),
              },
              {
                key: 'when',
                header: 'When',
                headClassName: 'text-right',
                cellClassName: 'text-right text-muted-foreground text-sm',
                cell: (event) => formatDate(event.occurred_at),
              },
            ]}
          />
        </Card>
      )}
    </PageShell>
  );
}
